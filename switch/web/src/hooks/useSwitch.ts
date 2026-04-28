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
  tool: string
  mode: 'pty'
  created_at: string
  needs_input: boolean
  needs_input_reason: string | null
}

interface SwitchState {
  connected: boolean
  daemons: Daemon[]
  sessions: Map<string, SessionInfo[]>
  ptyOutput: Map<string, string[]>  // sessionId -> raw terminal output chunks
}

interface ServerMessage {
  type?: string
  daemonId?: string
  sessionId?: string
  session?: SessionInfo
  sessions?: SessionInfo[]
  data?: unknown
  ptyOutput?: string[]
  reason?: string
  source?: string
}

export function useSwitch() {
  const wsRef = useRef<WebSocket | null>(null)
  const [state, setState] = useState<SwitchState>({
    connected: false,
    daemons: [],
    sessions: new Map(),
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

  const updateSessionInputRequired = useCallback((
    sessionId: string,
    needsInput: boolean,
    reason: string | null = null,
  ) => {
    setState(s => {
      const sessions = new Map(s.sessions)
      for (const [did, list] of sessions) {
        sessions.set(did, list.map(sess =>
          sess.id === sessionId
            ? { ...sess, needs_input: needsInput, needs_input_reason: needsInput ? reason : null }
            : sess
        ))
      }
      return { ...s, sessions }
    })
  }, [])

  const handleMessage = useCallback((msg: ServerMessage) => {
    const { type, daemonId, sessionId } = msg

    switch (type) {
      case 'session.list': {
        if (!daemonId || !msg.sessions) return
        setState(s => {
          const sessions = new Map(s.sessions)
          sessions.set(daemonId, (msg.sessions || [])
            .filter(session => session.mode === 'pty')
            .map(normalizeSession))
          return { ...s, sessions }
        })
        break
      }

      case 'pty.created': {
        if (!daemonId || !msg.session) return
        const session = normalizeSession(msg.session)
        setState(s => {
          const sessions = new Map(s.sessions)
          const list = sessions.get(daemonId) || []
          if (list.some(s => s.id === session.id)) return s
          sessions.set(daemonId, [...list, session])
          return { ...s, sessions }
        })
        break
      }

      case 'session.subscribed': {
        if (!daemonId || !msg.session) return
        const session = normalizeSession(msg.session)
        setState(s => {
          const sessions = new Map(s.sessions)
          const list = sessions.get(daemonId) || []
          sessions.set(daemonId, upsertSession(list, session))

          const ptyOutput = new Map(s.ptyOutput)
          if (Array.isArray(msg.ptyOutput)) {
            ptyOutput.set(session.id, msg.ptyOutput)
          }

          return { ...s, sessions, ptyOutput }
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
        updateSessionInputRequired(sessionId, false)
        updateSessionStatus(sessionId, 'stopped')
        break
      }

      case 'session.input_required': {
        if (!sessionId) return
        updateSessionInputRequired(sessionId, true, msg.reason || 'Human input required')
        break
      }

      case 'session.input_resolved': {
        if (!sessionId) return
        updateSessionInputRequired(sessionId, false)
        break
      }
    }
  }, [updateSessionInputRequired, updateSessionStatus])

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
    if (data) updateSessionInputRequired(sessionId, false)
  }, [send, updateSessionInputRequired])

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

  const subscribeSession = useCallback((daemonId: string, sessionId: string) => {
    send({ type: 'session.subscribe', daemonId, sessionId })
  }, [send])

  return {
    ...state,
    createPtySession,
    sendPtyInput,
    resizePty,
    stopSession,
    listSessions,
    subscribeSession,
    fetchDaemons,
  }
}

function normalizeSession(session: SessionInfo): SessionInfo {
  return {
    ...session,
    mode: 'pty',
    needs_input: Boolean(session.needs_input),
    needs_input_reason: session.needs_input_reason || null,
  }
}

function upsertSession(list: SessionInfo[], session: SessionInfo): SessionInfo[] {
  if (list.some(s => s.id === session.id)) {
    return list.map(s => s.id === session.id ? session : s)
  }
  return [...list, session]
}
