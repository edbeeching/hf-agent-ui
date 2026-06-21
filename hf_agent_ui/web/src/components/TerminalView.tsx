import { useCallback, useEffect, useRef, useState, type ClipboardEvent, type FormEvent } from 'react'
import { Terminal } from 'xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import type { InputRequiredKind, SessionImagePayload } from '../hooks/useAgentUi'
import 'xterm/css/xterm.css'

const MAX_PASTE_IMAGE_BYTES = 8 * 1024 * 1024
const DEFAULT_SCREENSHOT_PROMPT = 'Use this screenshot as context.'
const ALLOWED_PASTE_IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp'])
const MIN_TERMINAL_FIT_SIZE = 24

interface Props {
  sessionId: string
  onInput: (data: string) => void
  onResize: (cols: number, rows: number) => void
  onSendImage?: (image: SessionImagePayload) => void
  output: string[]
  outputEpoch?: number
  visible?: boolean
  needsInput?: boolean
  inputReason?: string | null
  inputKind?: InputRequiredKind | null
  tool?: string
}

export function TerminalView({
  sessionId,
  onInput,
  onResize,
  onSendImage,
  output,
  outputEpoch = 0,
  visible = true,
  needsInput = false,
  inputReason = null,
  inputKind = null,
  tool,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const termRef = useRef<Terminal | null>(null)
  const fitRef = useRef<FitAddon | null>(null)
  const writtenRef = useRef(0)
  const outputEpochRef = useRef(outputEpoch)
  const onInputRef = useRef(onInput)
  const onResizeRef = useRef(onResize)
  const pendingPreviewUrlRef = useRef<string | null>(null)
  const followOutputRef = useRef(true)
  const userScrollLockRef = useRef(false)
  const layoutFrameRef = useRef<number | null>(null)
  const settledLayoutFrameRef = useRef<number | null>(null)
  const settledLayoutTimeoutRef = useRef<number | null>(null)
  const scrollFrameRef = useRef<number | null>(null)
  const visibleRef = useRef(visible)
  const [pendingScreenshot, setPendingScreenshot] = useState<PendingScreenshot | null>(null)
  const [pasteNotice, setPasteNotice] = useState<string | null>(null)
  const [showScrollButton, setShowScrollButton] = useState(false)

  const stopFollowingOutput = useCallback((): void => {
    userScrollLockRef.current = true
    followOutputRef.current = false
    if (scrollFrameRef.current !== null) {
      window.cancelAnimationFrame(scrollFrameRef.current)
      scrollFrameRef.current = null
    }
    setShowScrollButton(true)
  }, [])

  const scheduleTerminalScroll = useCallback((forceFollow = false): void => {
    if (!termRef.current) return
    if (!visibleRef.current) {
      if (scrollFrameRef.current !== null) {
        window.cancelAnimationFrame(scrollFrameRef.current)
        scrollFrameRef.current = null
      }
      return
    }
    if (scrollFrameRef.current !== null) {
      window.cancelAnimationFrame(scrollFrameRef.current)
    }
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      scrollFrameRef.current = null
      if (!visibleRef.current) return
      const term = termRef.current
      if (!term) return
      if (forceFollow) {
        userScrollLockRef.current = false
        followOutputRef.current = true
      }
      if (forceFollow || (!userScrollLockRef.current && (followOutputRef.current || isTerminalAtBottom(term)))) {
        scrollTerminalToBottom(term)
        setShowScrollButton(false)
      } else {
        setShowScrollButton(true)
      }
    })
  }, [])

  const cancelImmediateTerminalFit = useCallback((): void => {
    if (layoutFrameRef.current !== null) {
      window.cancelAnimationFrame(layoutFrameRef.current)
      layoutFrameRef.current = null
    }
  }, [])

  const cancelSettledTerminalFit = useCallback((): void => {
    if (settledLayoutFrameRef.current !== null) {
      window.cancelAnimationFrame(settledLayoutFrameRef.current)
      settledLayoutFrameRef.current = null
    }
    if (settledLayoutTimeoutRef.current !== null) {
      window.clearTimeout(settledLayoutTimeoutRef.current)
      settledLayoutTimeoutRef.current = null
    }
  }, [])

  const runTerminalFit = useCallback((follow: boolean, forceFollow = false): boolean => {
    const terminalElement = containerRef.current
    const term = termRef.current
    const fitAddon = fitRef.current
    if (!visibleRef.current || !terminalElement || !term || !fitAddon) return false

    const { width, height } = terminalElement.getBoundingClientRect()
    if (width < MIN_TERMINAL_FIT_SIZE || height < MIN_TERMINAL_FIT_SIZE) {
      return false
    }

    fitAddon.fit()
    if (forceFollow) {
      userScrollLockRef.current = false
      followOutputRef.current = true
    }
    if (follow && (forceFollow || (!userScrollLockRef.current && followOutputRef.current))) {
      scrollTerminalToBottom(term)
      setShowScrollButton(false)
    } else {
      setShowScrollButton(!isTerminalAtBottom(term))
    }
    return true
  }, [])

  const scheduleTerminalFit = useCallback((follow: boolean, forceFollow = false): void => {
    if (!termRef.current || !fitRef.current) return
    if (!visibleRef.current) {
      cancelImmediateTerminalFit()
      return
    }
    cancelImmediateTerminalFit()
    layoutFrameRef.current = window.requestAnimationFrame(() => {
      layoutFrameRef.current = null
      runTerminalFit(follow, forceFollow)
    })
  }, [cancelImmediateTerminalFit, runTerminalFit])

  const scheduleSettledTerminalFit = useCallback((follow: boolean, forceFollow = false): void => {
    if (!termRef.current || !fitRef.current) return
    if (!visibleRef.current) {
      cancelImmediateTerminalFit()
      cancelSettledTerminalFit()
      return
    }

    scheduleTerminalFit(follow, forceFollow)
    cancelSettledTerminalFit()
    settledLayoutFrameRef.current = window.requestAnimationFrame(() => {
      settledLayoutFrameRef.current = null
      settledLayoutFrameRef.current = window.requestAnimationFrame(() => {
        settledLayoutFrameRef.current = null
        runTerminalFit(follow, forceFollow)
      })
    })
    settledLayoutTimeoutRef.current = window.setTimeout(() => {
      settledLayoutTimeoutRef.current = null
      runTerminalFit(follow, forceFollow)
    }, 120)
  }, [
    cancelImmediateTerminalFit,
    cancelSettledTerminalFit,
    runTerminalFit,
    scheduleTerminalFit,
  ])

  useEffect(() => {
    visibleRef.current = visible
    if (!visible) {
      cancelImmediateTerminalFit()
      cancelSettledTerminalFit()
    }
    if (!visible && scrollFrameRef.current !== null) {
      window.cancelAnimationFrame(scrollFrameRef.current)
      scrollFrameRef.current = null
    }
  }, [cancelImmediateTerminalFit, cancelSettledTerminalFit, visible])

  useEffect(() => {
    onInputRef.current = onInput
  }, [onInput])

  useEffect(() => {
    onResizeRef.current = onResize
  }, [onResize])

  useEffect(() => {
    return () => {
      if (pendingPreviewUrlRef.current) {
        URL.revokeObjectURL(pendingPreviewUrlRef.current)
        pendingPreviewUrlRef.current = null
      }
      if (layoutFrameRef.current !== null) {
        window.cancelAnimationFrame(layoutFrameRef.current)
        layoutFrameRef.current = null
      }
      if (settledLayoutFrameRef.current !== null) {
        window.cancelAnimationFrame(settledLayoutFrameRef.current)
        settledLayoutFrameRef.current = null
      }
      if (settledLayoutTimeoutRef.current !== null) {
        window.clearTimeout(settledLayoutTimeoutRef.current)
        settledLayoutTimeoutRef.current = null
      }
      if (scrollFrameRef.current !== null) {
        window.cancelAnimationFrame(scrollFrameRef.current)
        scrollFrameRef.current = null
      }
    }
  }, [])

  // Initialize terminal
  useEffect(() => {
    if (!containerRef.current || termRef.current) return
    const terminalElement = containerRef.current

    const term = new Terminal({
      cursorBlink: true,
      fontSize: terminalFontSize(),
      fontFamily: "'SF Mono', 'Fira Code', 'Cascadia Code', 'Menlo', monospace",
      linkHandler: {
        allowNonHttpProtocols: false,
        activate: (_event, uri) => openTerminalLink(uri),
      },
      theme: {
        background: '#0d1117',
        foreground: '#e6edf3',
        cursor: '#e6edf3',
        selectionBackground: '#1f6feb44',
        black: '#0d1117',
        red: '#f85149',
        green: '#3fb950',
        yellow: '#d29922',
        blue: '#1f6feb',
        magenta: '#bc8cff',
        cyan: '#76e3ea',
        white: '#e6edf3',
        brightBlack: '#484f58',
        brightRed: '#ff7b72',
        brightGreen: '#56d364',
        brightYellow: '#e3b341',
        brightBlue: '#79c0ff',
        brightMagenta: '#d2a8ff',
        brightCyan: '#b3f0ff',
        brightWhite: '#f0f6fc',
      },
    })

    const fitAddon = new FitAddon()
    const webLinksAddon = new WebLinksAddon((_event, uri) => openTerminalLink(uri))
    term.loadAddon(fitAddon)
    term.loadAddon(webLinksAddon)
    term.open(terminalElement)
    configureTerminalTextarea(terminalElement)
    followOutputRef.current = true
    setShowScrollButton(false)

    // Send keystrokes to the session
    term.onData((data) => {
      userScrollLockRef.current = false
      followOutputRef.current = true
      scheduleTerminalScroll(true)
      onInputRef.current(data)
    })

    // Handle resize
    term.onResize(({ cols, rows }) => {
      onResizeRef.current(cols, rows)
    })

    // Window resize
    const handleResize = () => {
      term.options.fontSize = terminalFontSize()
      scheduleTerminalFit(followOutputRef.current)
    }
    window.addEventListener('resize', handleResize)
    const observer = new ResizeObserver(handleResize)
    observer.observe(terminalElement)
    const handleWheel = (event: WheelEvent) => {
      if (event.deltaY < 0) {
        stopFollowingOutput()
      }
    }
    terminalElement.addEventListener('wheel', handleWheel, { passive: true })
    const scrollDisposable = term.onScroll(() => {
      const atBottom = isTerminalAtBottom(term)
      if (atBottom) {
        userScrollLockRef.current = false
        followOutputRef.current = true
      } else {
        userScrollLockRef.current = true
        followOutputRef.current = false
      }
      setShowScrollButton(!atBottom)
    })

    termRef.current = term
    fitRef.current = fitAddon
    scheduleSettledTerminalFit(true, true)

    return () => {
      window.removeEventListener('resize', handleResize)
      terminalElement.removeEventListener('wheel', handleWheel)
      observer.disconnect()
      scrollDisposable.dispose()
      cancelImmediateTerminalFit()
      cancelSettledTerminalFit()
      if (scrollFrameRef.current !== null) {
        window.cancelAnimationFrame(scrollFrameRef.current)
        scrollFrameRef.current = null
      }
      term.dispose()
      termRef.current = null
      fitRef.current = null
      writtenRef.current = 0
      followOutputRef.current = true
      userScrollLockRef.current = false
    }
  }, [
    cancelImmediateTerminalFit,
    cancelSettledTerminalFit,
    scheduleSettledTerminalFit,
    scheduleTerminalFit,
    scheduleTerminalScroll,
    sessionId,
    stopFollowingOutput,
  ])

  useEffect(() => {
    if (outputEpochRef.current === outputEpoch) return
    outputEpochRef.current = outputEpoch
    writtenRef.current = 0
    const term = termRef.current
    if (!term) return
    term.clear()
    setShowScrollButton(false)
  }, [outputEpoch])

  // Write new output to terminal
  useEffect(() => {
    const term = termRef.current
    if (!term) return
    let start = writtenRef.current
    if (output.length < start) {
      term.clear()
      writtenRef.current = 0
      start = 0
      setShowScrollButton(false)
    }
    if (start >= output.length) return
    const shouldFollow = !userScrollLockRef.current && (followOutputRef.current || isTerminalAtBottom(term))
    for (let i = start; i < output.length; i++) {
      const chunk = output[i]
      if (i === output.length - 1 && shouldFollow) {
        term.write(chunk, () => {
          scheduleTerminalScroll()
        })
      } else {
        term.write(chunk)
      }
    }
    writtenRef.current = output.length
    if (!shouldFollow) {
      setShowScrollButton(true)
    }
  }, [output, scheduleTerminalScroll])

  useEffect(() => {
    if (!visible || !fitRef.current) return
    scheduleSettledTerminalFit(followOutputRef.current)
  }, [visible, sessionId, needsInput, scheduleSettledTerminalFit])

  if (!sessionId) {
    return (
      <div className="session-view-empty">
        Select a session or create a new one
      </div>
    )
  }

  function handlePaste(event: ClipboardEvent<HTMLDivElement>): void {
    const image = imageFileFromClipboard(event.clipboardData)
    if (!image) return
    event.preventDefault()
    setPasteNotice(null)

    if (tool !== 'codex') {
      setPasteNotice('Screenshot paste is currently supported for Codex sessions only.')
      return
    }
    if (!onSendImage) {
      setPasteNotice('Screenshot paste is unavailable for this session.')
      return
    }
    if (!ALLOWED_PASTE_IMAGE_TYPES.has(image.type)) {
      setPasteNotice('Unsupported screenshot type.')
      return
    }
    if (image.size > MAX_PASTE_IMAGE_BYTES) {
      setPasteNotice('Screenshot is too large.')
      return
    }

    const previewUrl = URL.createObjectURL(image)
    if (pendingPreviewUrlRef.current) {
      URL.revokeObjectURL(pendingPreviewUrlRef.current)
    }
    pendingPreviewUrlRef.current = previewUrl
    setPendingScreenshot({
      file: image,
      previewUrl,
      prompt: DEFAULT_SCREENSHOT_PROMPT,
      sending: false,
      error: null,
    })
  }

  async function handleScreenshotSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    if (!pendingScreenshot || !onSendImage) return

    setPendingScreenshot(current => current ? { ...current, sending: true, error: null } : current)
    try {
      const dataBase64 = await fileToBase64(pendingScreenshot.file)
      onSendImage({
        filename: pendingScreenshot.file.name || fallbackImageFilename(pendingScreenshot.file.type),
        mimeType: pendingScreenshot.file.type,
        dataBase64,
        prompt: pendingScreenshot.prompt.trim() || DEFAULT_SCREENSHOT_PROMPT,
      })
      URL.revokeObjectURL(pendingScreenshot.previewUrl)
      pendingPreviewUrlRef.current = null
      setPendingScreenshot(null)
      setPasteNotice('Screenshot sent to Codex.')
    } catch {
      setPendingScreenshot(current => current ? {
        ...current,
        sending: false,
        error: 'Could not read screenshot data.',
      } : current)
    }
  }

  function closeScreenshotDialog(): void {
    setPendingScreenshot(current => {
      if (current) URL.revokeObjectURL(current.previewUrl)
      pendingPreviewUrlRef.current = null
      return null
    })
  }

  function handleScrollToBottom(): void {
    if (!termRef.current) return
    userScrollLockRef.current = false
    followOutputRef.current = true
    scheduleTerminalScroll(true)
    setShowScrollButton(false)
  }

  return (
    <div className={`terminal-shell ${needsInput ? 'needs-input' : ''}`} onPasteCapture={handlePaste}>
      {needsInput && (
        <div className="input-required-banner" role="status">
          <span className={`input-required-banner-label ${inputKind || 'prompt'}`}>
            {inputKindLabel(inputKind)}
          </span>
          <span className="input-required-banner-reason">
            {inputReason || `${toolLabel(tool)} is waiting for a response`}
          </span>
        </div>
      )}
      {pasteNotice && (
        <div className="screenshot-paste-notice" role="status">
          {pasteNotice}
          <button type="button" onClick={() => setPasteNotice(null)} aria-label="Dismiss screenshot notice">
            x
          </button>
        </div>
      )}
      {pendingScreenshot && (
        <form className="screenshot-paste-card" onSubmit={handleScreenshotSubmit}>
          <img src={pendingScreenshot.previewUrl} alt="Pasted screenshot preview" />
          <label>
            Prompt
            <textarea
              value={pendingScreenshot.prompt}
              onChange={(event) => setPendingScreenshot(current => current ? {
                ...current,
                prompt: event.target.value,
                error: null,
              } : current)}
              rows={3}
              disabled={pendingScreenshot.sending}
            />
          </label>
          {pendingScreenshot.error && (
            <div className="screenshot-paste-error">{pendingScreenshot.error}</div>
          )}
          <div className="screenshot-paste-actions">
            <button type="button" onClick={closeScreenshotDialog} disabled={pendingScreenshot.sending}>
              Cancel
            </button>
            <button type="submit" disabled={pendingScreenshot.sending}>
              {pendingScreenshot.sending ? 'Sending' : 'Send'}
            </button>
          </div>
        </form>
      )}
      <div ref={containerRef} className="terminal-container" />
      {showScrollButton && (
        <button
          type="button"
          className="terminal-scroll-bottom"
          onClick={handleScrollToBottom}
          aria-label="Scroll to latest terminal output"
          title="Scroll to bottom"
        >
          ↓
        </button>
      )}
    </div>
  )
}

interface PendingScreenshot {
  file: File
  previewUrl: string
  prompt: string
  sending: boolean
  error: string | null
}

function terminalFontSize(): number {
  return window.matchMedia('(max-width: 760px)').matches ? 12 : 13
}

function configureTerminalTextarea(container: HTMLElement): void {
  const textarea = container.querySelector('textarea')
  if (!textarea) return
  textarea.setAttribute('autocorrect', 'off')
  textarea.setAttribute('autocapitalize', 'none')
  textarea.setAttribute('autocomplete', 'off')
  textarea.spellcheck = false
}

function isTerminalAtBottom(term: Terminal): boolean {
  const buffer = term.buffer.active
  return buffer.baseY - buffer.viewportY <= 1
}

function scrollTerminalToBottom(term: Terminal): void {
  term.scrollToBottom()
  followTerminalOutput(term)
}

function followTerminalOutput(term: Terminal): void {
  const buffer = term.buffer.active
  if (buffer.baseY - buffer.viewportY <= 1) {
    return
  }
  term.scrollToLine(buffer.baseY)
}

function openTerminalLink(uri: string): void {
  const url = safeTerminalLink(uri)
  if (!url) return

  const anchor = document.createElement('a')
  anchor.href = url
  anchor.target = '_blank'
  anchor.rel = 'noopener noreferrer'
  anchor.referrerPolicy = 'no-referrer'
  anchor.style.display = 'none'
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
}

function safeTerminalLink(uri: string): string | null {
  try {
    const url = new URL(uri)
    if (url.protocol === 'http:' || url.protocol === 'https:') {
      return url.toString()
    }
  } catch {
    return null
  }
  return null
}

function imageFileFromClipboard(data: DataTransfer): File | null {
  for (const item of data.items) {
    if (!item.type.startsWith('image/')) continue
    const file = item.getAsFile()
    if (file) return file
  }
  return null
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(reader.error)
    reader.onload = () => {
      const result = reader.result
      if (typeof result !== 'string') {
        reject(new Error('Unexpected file reader result'))
        return
      }
      resolve(result.split(',', 2)[1] || '')
    }
    reader.readAsDataURL(file)
  })
}

function fallbackImageFilename(mimeType: string): string {
  if (mimeType === 'image/jpeg') return 'screenshot.jpg'
  if (mimeType === 'image/webp') return 'screenshot.webp'
  return 'screenshot.png'
}

function toolLabel(tool?: string): string {
  if (tool === 'codex') return 'Codex'
  if (tool === 'bash') return 'Bash'
  return 'Claude'
}

function inputKindLabel(kind: InputRequiredKind | null): string {
  if (kind === 'permission') return 'Permission'
  if (kind === 'confirmation') return 'Confirm'
  if (kind === 'auth') return 'Auth'
  return 'Input needed'
}
