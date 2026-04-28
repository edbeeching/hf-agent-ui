import { useCallback, useEffect, useRef, useState } from 'react'

type JsonObject = Record<string, unknown>

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
  data?: unknown
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

interface CreateSessionOptions {
  tool?: string
  model?: string
  permissionMode?: string
  initialPrompt?: string
}

interface ServerMessage {
  type?: string
  daemonId?: string
  sessionId?: string
  session?: SessionInfo
  sessions?: SessionInfo[]
  data?: unknown
  text?: string
  code?: number | null
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

  const updateSessionStatus = useCallback((sessionId: string, status: string) => {
    setState(s => {
      const sessions = new Map(s.sessions)
      for (const [did, list] of sessions) {
        sessions.set(did, list.map(sess =>
          sess.id === sessionId ? { ...sess, status } : sess
        ))
      }
      return { ...s, sessions }
    })
  }, [])

  const handleMessage = useCallback((msg: ServerMessage) => {
    const { type, daemonId, sessionId } = msg

    switch (type) {
      // === JSON mode ===
      case 'session.created': {
        if (!daemonId || !msg.session) return
        const session = { ...msg.session, mode: 'json' } as SessionInfo
        setState(s => {
          const sessions = new Map(s.sessions)
          const list = sessions.get(daemonId) || []
          if (list.some(s => s.id === session.id)) return s  // deduplicate
          sessions.set(daemonId, [...list, session])
          return { ...s, sessions }
        })
        break
      }

      case 'session.message':
      case 'session.stderr':
      case 'session.exit':
      case 'session.started': {
        if (!daemonId || !sessionId) return
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
          updateSessionStatus(sessionId, 'stopped')
        }
        break
      }

      case 'session.list': {
        if (!daemonId || !msg.sessions) return
        setState(s => {
          const sessions = new Map(s.sessions)
          sessions.set(daemonId, msg.sessions || [])
          return { ...s, sessions }
        })
        break
      }

      // === PTY mode ===
      case 'pty.created': {
        if (!daemonId || !msg.session) return
        const session = { ...msg.session, mode: 'pty' } as SessionInfo
        setState(s => {
          const sessions = new Map(s.sessions)
          const list = sessions.get(daemonId) || []
          if (list.some(s => s.id === session.id)) return s
          sessions.set(daemonId, [...list, session])
          return { ...s, sessions }
        })
        break
      }

      case 'pty.output': {
        if (!sessionId || typeof msg.data !== 'string') return
        setState(s => {
          const ptyOutput = new Map(s.ptyOutput)
          const chunks = ptyOutput.get(sessionId) || []
          ptyOutput.set(sessionId, [...chunks, msg.data as string])
          return { ...s, ptyOutput }
        })
        break
      }

      case 'pty.started': {
        // Already handled by pty.created
        break
      }

      case 'pty.exit': {
        if (!sessionId) return
        updateSessionStatus(sessionId, 'stopped')
        break
      }
    }
  }, [updateSessionStatus])

  useEffect(() => {
    let disposed = false
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws`

    function connect() {
      if (disposed) return
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        if (disposed) { ws.close(); return }
        setState(s => ({ ...s, connected: true }))
        fetchDaemons()
      }

      ws.onclose = () => {
        if (disposed) return
        setState(s => ({ ...s, connected: false }))
        setTimeout(connect, 2000)
      }

      ws.onmessage = (event) => {
        if (disposed) return
        const msg = JSON.parse(event.data) as ServerMessage
        handleMessage(msg)
      }
    }

    connect()

    const interval = setInterval(fetchDaemons, 10000)

    return () => {
      disposed = true
      clearInterval(interval)
      wsRef.current?.close()
    }
  }, [fetchDaemons, handleMessage])

  const send = useCallback((data: JsonObject) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data))
    }
  }, [])

  // JSON mode
  const createSession = useCallback((
    daemonId: string,
    workDir: string,
    opts?: CreateSessionOptions,
  ) => {
    send({ type: 'session.create', daemonId, workDir, ...opts })
  }, [send])

  const sendMessage = useCallback((daemonId: string, sessionId: string, message: string) => {
    send({ type: 'session.send', daemonId, sessionId, message })
  }, [send])

  const sendControl = useCallback((daemonId: string, sessionId: string, response: unknown) => {
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
