import { useEffect, useRef } from 'react'
import { Terminal } from 'xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import 'xterm/css/xterm.css'

interface Props {
  sessionId: string
  onInput: (data: string) => void
  onResize: (cols: number, rows: number) => void
  output: string[]
  visible?: boolean
  needsInput?: boolean
  inputReason?: string | null
  tool?: string
}

export function TerminalView({
  sessionId,
  onInput,
  onResize,
  output,
  visible = true,
  needsInput = false,
  inputReason = null,
  tool,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const termRef = useRef<Terminal | null>(null)
  const fitRef = useRef<FitAddon | null>(null)
  const writtenRef = useRef(0)
  const onInputRef = useRef(onInput)
  const onResizeRef = useRef(onResize)

  useEffect(() => {
    onInputRef.current = onInput
  }, [onInput])

  useEffect(() => {
    onResizeRef.current = onResize
  }, [onResize])

  // Initialize terminal
  useEffect(() => {
    if (!containerRef.current || termRef.current) return

    const term = new Terminal({
      cursorBlink: true,
      fontSize: terminalFontSize(),
      fontFamily: "'SF Mono', 'Fira Code', 'Cascadia Code', 'Menlo', monospace",
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
    const webLinksAddon = new WebLinksAddon()
    term.loadAddon(fitAddon)
    term.loadAddon(webLinksAddon)
    term.open(containerRef.current)
    fitAddon.fit()

    // Send keystrokes to the session
    term.onData((data) => {
      onInputRef.current(data)
    })

    // Handle resize
    term.onResize(({ cols, rows }) => {
      onResizeRef.current(cols, rows)
    })

    // Window resize
    const handleResize = () => {
      term.options.fontSize = terminalFontSize()
      fitAddon.fit()
    }
    window.addEventListener('resize', handleResize)
    const observer = new ResizeObserver(handleResize)
    observer.observe(containerRef.current)

    termRef.current = term
    fitRef.current = fitAddon

    return () => {
      window.removeEventListener('resize', handleResize)
      observer.disconnect()
      term.dispose()
      termRef.current = null
      fitRef.current = null
      writtenRef.current = 0
    }
  }, [sessionId])

  // Write new output to terminal
  useEffect(() => {
    if (!termRef.current) return
    const start = writtenRef.current
    for (let i = start; i < output.length; i++) {
      termRef.current.write(output[i])
    }
    writtenRef.current = output.length
  }, [output])

  useEffect(() => {
    if (!visible || !fitRef.current) return
    const frame = window.requestAnimationFrame(() => fitRef.current?.fit())
    return () => window.cancelAnimationFrame(frame)
  }, [visible, sessionId])

  if (!sessionId) {
    return (
      <div className="session-view-empty">
        Select a session or create a new one
      </div>
    )
  }

  return (
    <div className={`terminal-shell ${needsInput ? 'needs-input' : ''}`}>
      {needsInput && (
        <div className="input-required-banner" role="status">
          <span className="input-required-banner-label">Input needed</span>
          <span className="input-required-banner-reason">
            {inputReason || `${toolLabel(tool)} is waiting for a response`}
          </span>
        </div>
      )}
      <div ref={containerRef} className="terminal-container" />
    </div>
  )
}

function terminalFontSize(): number {
  return window.matchMedia('(max-width: 760px)').matches ? 12 : 13
}

function toolLabel(tool?: string): string {
  if (tool === 'codex') return 'Codex'
  if (tool === 'bash') return 'Bash'
  return 'Claude'
}
