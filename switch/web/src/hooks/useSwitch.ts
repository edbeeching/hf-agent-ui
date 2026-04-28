import { useCallback, useEffect, useRef, useState } from 'react'

export interface Daemon {
  id: string
  name: string
  host: string
  port: number
  hostname: string
  connected: boolean
}

export interface SessionInfo {
  id: string
  status: string
  work_dir: string
  model: string | null
  tool: string
  mode?: string  // "pty" or "json" (default)
  created_at: string
}

export interface SessionMessage {
  id: string
  daemonId: string
  sessionId: string
  type: 'message' | 'stderr' | 'exit' | 'started'
  data?: any
  text?: string
  code?: number | null
  timestamp: string
}

interface SwitchState {
  connected: boolean
  daemons: Daemon[]
  sessions: Map<string, SessionInfo[]>
  messages: Map<string, SessionMessage[]>
  ptyOutput: Map<string, string[]>  // sessionId -> raw terminal output chunks
}

export function useSwitch() {
  const wsRef = useRef<WebSocket | null>(null)
  const [state, setState] = useState<SwitchState>({
    connected: false,
    daemons: [],
    sessions: new Map(),
    messages: new Map(),
    ptyOutput: new Map(),
  })

  const fetchDaemons = useCallback(async () => {
    try {
      const res = await fetch('/api/daemons')
      const daemons: Daemon[] = await res.json()
      setState(s => ({ ...s, daemons }))
    } catch {
      // Hub not available
    }
  }, [])

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws`

    function connect() {
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        setState(s => ({ ...s, connected: true }))
        fetchDaemons()
      }

      ws.onclose = () => {
        setState(s => ({ ...s, connected: false }))
        setTimeout(connect, 2000)
      }

      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data)
        handleMessage(msg)
      }
    }

    connect()

    const interval = setInterval(fetchDaemons, 10000)

    return () => {
      clearInterval(interval)
      wsRef.current?.close()
    }
  }, [fetchDaemons])

  function handleMessage(msg: any) {
    const { type, daemonId, sessionId } = msg

    switch (type) {
      // === JSON mode ===
      case 'session.created': {
        const session = { ...msg.session, mode: 'json' } as SessionInfo
        setState(s => {
          const sessions = new Map(s.sessions)
          const list = sessions.get(daemonId) || []
          sessions.set(daemonId, [...list, session])
          return { ...s, sessions }
        })
        break
      }

      case 'session.message':
      case 'session.stderr':
      case 'session.exit':
      case 'session.started': {
        const entry: SessionMessage = {
          id: crypto.randomUUID(),
          daemonId,
          sessionId,
          type: type.replace('session.', '') as SessionMessage['type'],
          data: msg.data,
          text: msg.text,
          code: msg.code,
          timestamp: new Date().toISOString(),
        }
        setState(s => {
          const messages = new Map(s.messages)
          const list = messages.get(sessionId) || []
          messages.set(sessionId, [...list, entry])
          return { ...s, messages }
        })

        if (type === 'session.exit') {
          _updateSessionStatus(daemonId, sessionId, 'stopped')
        }
        break
      }

      case 'session.list': {
        setState(s => {
          const sessions = new Map(s.sessions)
          sessions.set(daemonId, msg.sessions)
          return { ...s, sessions }
        })
        break
      }

      // === PTY mode ===
      case 'pty.created': {
        const session = { ...msg.session, mode: 'pty' } as SessionInfo
        setState(s => {
          const sessions = new Map(s.sessions)
          const list = sessions.get(daemonId) || []
          sessions.set(daemonId, [...list, session])
          return { ...s, sessions }
        })
        break
      }

      case 'pty.output': {
        setState(s => {
          const ptyOutput = new Map(s.ptyOutput)
          const chunks = ptyOutput.get(sessionId) || []
          ptyOutput.set(sessionId, [...chunks, msg.data])
          return { ...s, ptyOutput }
        })
        break
      }

      case 'pty.started': {
        // Already handled by pty.created
        break
      }

      case 'pty.exit': {
        _updateSessionStatus(daemonId, sessionId, 'stopped')
        break
      }
    }
  }

  function _updateSessionStatus(_daemonId: string, sessionId: string, status: string) {
    setState(s => {
      const sessions = new Map(s.sessions)
      for (const [did, list] of sessions) {
        sessions.set(did, list.map(sess =>
          sess.id === sessionId ? { ...sess, status } : sess
        ))
      }
      return { ...s, sessions }
    })
  }

  const send = useCallback((data: any) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data))
    }
  }, [])

  // JSON mode
  const createSession = useCallback((
    daemonId: string,
    workDir: string,
    opts?: { tool?: string; model?: string; permissionMode?: string; initialPrompt?: string },
  ) => {
    send({ type: 'session.create', daemonId, workDir, ...opts })
  }, [send])

  const sendMessage = useCallback((daemonId: string, sessionId: string, message: string) => {
    send({ type: 'session.send', daemonId, sessionId, message })
  }, [send])

  const sendControl = useCallback((daemonId: string, sessionId: string, response: any) => {
    send({ type: 'session.control', daemonId, sessionId, response })
  }, [send])

  // PTY mode
  const createPtySession = useCallback((
    daemonId: string,
    workDir: string,
    tool: string = 'claude',
    cols: number = 120,
    rows: number = 40,
  ) => {
    send({ type: 'pty.create', daemonId, workDir, tool, cols, rows })
  }, [send])

  const sendPtyInput = useCallback((daemonId: string, sessionId: string, data: string) => {
    send({ type: 'pty.input', daemonId, sessionId, data })
  }, [send])

  const resizePty = useCallback((daemonId: string, sessionId: string, cols: number, rows: number) => {
    send({ type: 'pty.resize', daemonId, sessionId, cols, rows })
  }, [send])

  // Shared
  const stopSession = useCallback((daemonId: string, sessionId: string) => {
    send({ type: 'session.stop', daemonId, sessionId })
  }, [send])

  const listSessions = useCallback((daemonId: string) => {
    send({ type: 'session.list', daemonId })
  }, [send])

  return {
    ...state,
    createSession,
    sendMessage,
    sendControl,
    createPtySession,
    sendPtyInput,
    resizePty,
    stopSession,
    listSessions,
    fetchDaemons,
  }
}
