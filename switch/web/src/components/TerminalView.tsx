import { useEffect, useRef } from 'react'
import { Terminal } from 'xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import 'xterm/css/xterm.css'

interface Props {
  sessionId: string
  daemonId: string
  onInput: (data: string) => void
  onResize: (cols: number, rows: number) => void
  output: string[]
}

export function TerminalView({ sessionId, onInput, onResize, output }: Props) {
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
      fontSize: 13,
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
    const handleResize = () => fitAddon.fit()
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

  if (!sessionId) {
    return (
      <div className="session-view-empty">
        Select a session or create a new one
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      className="terminal-container"
      style={{ flex: 1, padding: 4, background: '#0d1117' }}
    />
  )
}
