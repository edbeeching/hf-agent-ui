import { useCallback, useEffect, useRef, useState, type ClipboardEvent, type FormEvent, type KeyboardEvent } from 'react'
import { Terminal } from 'xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import type { InputRequiredKind, SessionImagePayload } from '../hooks/useAgentUi'
import 'xterm/css/xterm.css'

const MAX_PASTE_IMAGE_BYTES = 8 * 1024 * 1024
const DEFAULT_SCREENSHOT_PROMPT = 'Use this screenshot as context.'
const ALLOWED_PASTE_IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp'])

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
  const layoutFrameRef = useRef<number | null>(null)
  const scrollFrameRef = useRef<number | null>(null)
  const visibleRef = useRef(visible)
  const [pendingScreenshot, setPendingScreenshot] = useState<PendingScreenshot | null>(null)
  const [pasteNotice, setPasteNotice] = useState<string | null>(null)
  const [showScrollButton, setShowScrollButton] = useState(false)
  const [mobileInput, setMobileInput] = useState('')

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
        followOutputRef.current = true
      }
      if (forceFollow || followOutputRef.current || isTerminalAtBottom(term)) {
        scrollTerminalToBottom(term)
        setShowScrollButton(false)
      } else {
        setShowScrollButton(true)
      }
    })
  }, [])

  const scheduleTerminalFit = useCallback((follow: boolean, forceFollow = false): void => {
    if (!termRef.current || !fitRef.current) return
    if (!visibleRef.current) {
      if (layoutFrameRef.current !== null) {
        window.cancelAnimationFrame(layoutFrameRef.current)
        layoutFrameRef.current = null
      }
      return
    }
    if (layoutFrameRef.current !== null) {
      window.cancelAnimationFrame(layoutFrameRef.current)
    }
    layoutFrameRef.current = window.requestAnimationFrame(() => {
      layoutFrameRef.current = null
      if (!visibleRef.current) return
      fitRef.current?.fit()
      const term = termRef.current
      if (!term) return
      if (follow && (forceFollow || followOutputRef.current)) {
        scrollTerminalToBottom(term)
        if (forceFollow) {
          followOutputRef.current = true
        }
        setShowScrollButton(false)
      } else {
        setShowScrollButton(!isTerminalAtBottom(term))
      }
    })
  }, [])

  useEffect(() => {
    visibleRef.current = visible
    if (!visible && layoutFrameRef.current !== null) {
      window.cancelAnimationFrame(layoutFrameRef.current)
      layoutFrameRef.current = null
    }
    if (!visible && scrollFrameRef.current !== null) {
      window.cancelAnimationFrame(scrollFrameRef.current)
      scrollFrameRef.current = null
    }
  }, [visible])

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
      if (scrollFrameRef.current !== null) {
        window.cancelAnimationFrame(scrollFrameRef.current)
        scrollFrameRef.current = null
      }
    }
  }, [])

  // Initialize terminal
  useEffect(() => {
    if (!containerRef.current || termRef.current) return

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
    term.open(containerRef.current)
    configureTerminalTextarea(containerRef.current)
    fitAddon.fit()
    followOutputRef.current = true
    setShowScrollButton(false)

    // Send keystrokes to the session
    term.onData((data) => {
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
    observer.observe(containerRef.current)
    const scrollDisposable = term.onScroll(() => {
      const atBottom = isTerminalAtBottom(term)
      followOutputRef.current = atBottom
      setShowScrollButton(!atBottom)
    })

    termRef.current = term
    fitRef.current = fitAddon

    return () => {
      window.removeEventListener('resize', handleResize)
      observer.disconnect()
      scrollDisposable.dispose()
      if (layoutFrameRef.current !== null) {
        window.cancelAnimationFrame(layoutFrameRef.current)
        layoutFrameRef.current = null
      }
      if (scrollFrameRef.current !== null) {
        window.cancelAnimationFrame(scrollFrameRef.current)
        scrollFrameRef.current = null
      }
      term.dispose()
      termRef.current = null
      fitRef.current = null
      writtenRef.current = 0
      followOutputRef.current = true
    }
  }, [scheduleTerminalFit, scheduleTerminalScroll, sessionId])

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
    const shouldFollow = followOutputRef.current || isTerminalAtBottom(term)
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
    scheduleTerminalFit(followOutputRef.current)
  }, [visible, sessionId, needsInput, scheduleTerminalFit])

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
    followOutputRef.current = true
    scheduleTerminalScroll(true)
    setShowScrollButton(false)
  }

  function sendTerminalInput(data: string): void {
    if (!data) return
    followOutputRef.current = true
    scheduleTerminalScroll(true)
    onInputRef.current(data)
  }

  function handleMobileSend(): void {
    const text = mobileInput
    if (!text) return
    sendTerminalInput(`${text}\r`)
    setMobileInput('')
  }

  function handleMobileKeyDown(event: KeyboardEvent<HTMLInputElement>): void {
    if (event.key !== 'Enter') return
    event.preventDefault()
    handleMobileSend()
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
      <div className="mobile-terminal-input" aria-label="Mobile terminal input">
        <div className="mobile-terminal-shortcuts">
          <button type="button" onClick={() => sendTerminalInput('\t')}>Tab</button>
          <button type="button" onClick={() => sendTerminalInput('\x1b')}>Esc</button>
          <button type="button" onClick={() => sendTerminalInput('\x03')}>Ctrl+C</button>
          <button type="button" onClick={() => sendTerminalInput('\r')}>Enter</button>
        </div>
        <div className="mobile-terminal-compose">
          <input
            type="text"
            value={mobileInput}
            onChange={event => setMobileInput(event.target.value)}
            onKeyDown={handleMobileKeyDown}
            placeholder="Type command"
            autoCapitalize="none"
            autoCorrect="off"
            autoComplete="off"
            spellCheck={false}
          />
          <button type="button" onClick={handleMobileSend} disabled={!mobileInput}>
            Send
          </button>
        </div>
      </div>
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
