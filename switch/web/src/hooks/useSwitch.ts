import { useCallback, useEffect, useRef, useState } from 'react'
import { initializeUiTokenFromUrl, uiAuthFetch, uiWebSocketUrl } from '../auth'

type JsonObject = Record<string, unknown>

initializeUiTokenFromUrl()

export type LaunchMode = 'local' | 'custom'

export interface LaunchOptions {
  launchMode: LaunchMode
  launchCommand?: string
  launchLabel?: string
}

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
  launch_mode: LaunchMode
  launch_command: string | null
  launch_label: string | null
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
  reason?: string
  source?: string
  status?: string
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
      const res = await uiAuthFetch('/api/daemons')
      const daemons: Daemon[] = await res.json()
      setState(s => {
        const daemonIds = new Set(daemons.map(daemon => daemon.id))
        const sessions = new Map(s.sessions)
        for (const daemonId of sessions.keys()) {
          if (!daemonIds.has(daemonId)) {
            sessions.delete(daemonId)
          }
        }
        return { ...s, daemons, sessions }
      })
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
          ptyOutput.set(session.id, [])

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
        updateSessionStatus(sessionId, msg.status || 'stopped')
        break
      }

      case 'session.paused':
      case 'session.resumed': {
        if (!daemonId || !sessionId || !msg.session) return
        const session = normalizeSession(msg.session)
        setState(s => {
          const sessions = new Map(s.sessions)
          const list = sessions.get(daemonId) || []
          sessions.set(daemonId, upsertSession(list, session))
          return { ...s, sessions }
        })
        break
      }

      case 'session.removed': {
        if (!daemonId || !sessionId) return
        setState(s => {
          const sessions = new Map(s.sessions)
          const list = sessions.get(daemonId) || []
          sessions.set(daemonId, list.filter(session => session.id !== sessionId))

          const ptyOutput = new Map(s.ptyOutput)
          ptyOutput.delete(sessionId)

          return { ...s, sessions, ptyOutput }
        })
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
    const wsUrl = uiWebSocketUrl('/ws')

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

    const interval = setInterval(fetchDaemons, 3000)

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

  useEffect(() => {
    if (!state.connected) return
    for (const daemon of state.daemons) {
      if (daemon.connected) {
        send({ type: 'session.list', daemonId: daemon.id })
      }
    }
  }, [send, state.connected, state.daemons])

  const createPtySession = useCallback((
    daemonId: string,
    workDir: string,
    tool: string = 'claude',
    launch: LaunchOptions = { launchMode: 'local' },
    cols: number = 120,
    rows: number = 40,
  ) => {
    send({
      type: 'pty.create',
      daemonId,
      workDir,
      tool,
      cols,
      rows,
      launchMode: launch.launchMode,
      launchCommand: launch.launchCommand,
      launchLabel: launch.launchLabel,
    })
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

  const removeSession = useCallback((daemonId: string, sessionId: string) => {
    send({ type: 'session.remove', daemonId, sessionId })
    setState(s => {
      const sessions = new Map(s.sessions)
      const list = sessions.get(daemonId) || []
      sessions.set(daemonId, list.filter(session => session.id !== sessionId))

      const ptyOutput = new Map(s.ptyOutput)
      ptyOutput.delete(sessionId)

      return { ...s, sessions, ptyOutput }
    })
  }, [send])

  const pauseSession = useCallback((daemonId: string, sessionId: string) => {
    send({ type: 'session.pause', daemonId, sessionId })
  }, [send])

  const resumeSession = useCallback((daemonId: string, sessionId: string) => {
    send({ type: 'session.resume', daemonId, sessionId })
  }, [send])

  const pauseDaemon = useCallback((daemonId: string) => {
    send({ type: 'app.pause', daemonId })
  }, [send])

  const resumeDaemon = useCallback((daemonId: string) => {
    send({ type: 'app.resume', daemonId })
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
    removeSession,
    pauseSession,
    resumeSession,
    pauseDaemon,
    resumeDaemon,
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
    launch_mode: session.launch_mode === 'custom' ? 'custom' : 'local',
    launch_command: typeof session.launch_command === 'string' ? session.launch_command : null,
    launch_label: typeof session.launch_label === 'string' ? session.launch_label : null,
  }
}

function upsertSession(list: SessionInfo[], session: SessionInfo): SessionInfo[] {
  if (list.some(s => s.id === session.id)) {
    return list.map(s => s.id === session.id ? session : s)
  }
  return [...list, session]
}
