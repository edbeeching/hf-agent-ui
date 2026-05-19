import { useCallback, useEffect, useRef, useState } from 'react'
import { ensureUiTokenCookie, initializeUiTokenFromUrl, uiAuthFetch, uiWebSocketUrl } from '../auth'

type JsonObject = Record<string, unknown>
const AGENT_WORKING_WINDOW_MS = 20_000

initializeUiTokenFromUrl()

export type LaunchMode = 'local' | 'custom'

export interface LaunchOptions {
  launchMode: LaunchMode
  launchCommand?: string
  launchLabel?: string
}

export interface WorktreeOptions {
  enabled: true
  sourceDir: string
  branch: string
  startPoint?: string
}

export interface SessionWorktreeInfo {
  source_dir: string
  repo_root: string
  worktree_root: string
  branch: string
  start_point: string
}

export type AgentState = 'blocked' | 'working' | 'done' | 'idle' | 'unknown'

export interface SessionGitInfo {
  branch: string | null
  dirty: boolean
  ahead: number | null
  behind: number | null
  is_worktree: boolean
  repo_root: string
}

export interface SessionImagePayload {
  filename: string
  mimeType: string
  dataBase64: string
  prompt: string
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
  label: string | null
  agent_state: AgentState
  last_activity_at: string | null
  last_seen_at: string | null
  done_since: string | null
  needs_input: boolean
  needs_input_reason: string | null
  needs_input_kind: InputRequiredKind | null
  needs_input_source: string | null
  needs_input_title: string | null
  needs_input_message: string | null
  needs_input_detected_at: string | null
  launch_mode: LaunchMode
  launch_command: string | null
  launch_label: string | null
  worktree: SessionWorktreeInfo | null
  git: SessionGitInfo | null
}

export type InputRequiredKind = 'permission' | 'confirmation' | 'auth' | 'prompt'

export interface AgentUiError {
  message: string
  requestType: string | null
  daemonId: string | null
}

interface AgentUiState {
  connected: boolean
  daemons: Daemon[]
  sessions: Map<string, SessionInfo[]>
  ptyOutput: Map<string, string[]>  // sessionId -> raw terminal output chunks
  lastError: AgentUiError | null
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
  kind?: string
  title?: string
  message?: string
  detectedAt?: string
  status?: string
  requestType?: string
}

interface InputRequiredUpdate {
  reason: string | null
  kind: InputRequiredKind | null
  source: string | null
  title: string | null
  message: string | null
  detectedAt: string | null
}

export function useAgentUi(enabled = true) {
  const wsRef = useRef<WebSocket | null>(null)
  const [state, setState] = useState<AgentUiState>({
    connected: false,
    daemons: [],
    sessions: new Map(),
    ptyOutput: new Map(),
    lastError: null,
  })

  const fetchDaemons = useCallback(async () => {
    if (!enabled) return
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
  }, [enabled])

  const updateSessionStatus = useCallback((sessionId: string, status: string) => {
    setState(s => {
      const sessions = updateSession(s.sessions, sessionId, session => refreshAgentState({ ...session, status }))
      return { ...s, sessions }
    })
  }, [])

  const updateSessionInputRequired = useCallback((
    sessionId: string,
    needsInput: boolean,
    update: Partial<InputRequiredUpdate> = {},
  ) => {
    setState(s => {
      const sessions = new Map(s.sessions)
      for (const [did, list] of sessions) {
        sessions.set(did, list.map(sess =>
          sess.id === sessionId
            ? {
              ...sess,
              agent_state: needsInput ? 'blocked' : refreshAgentState({ ...sess, needs_input: false }).agent_state,
              needs_input: needsInput,
              needs_input_reason: needsInput ? update.reason || 'Human input required' : null,
              needs_input_kind: needsInput ? normalizeInputRequiredKind(update.kind) : null,
              needs_input_source: needsInput ? update.source || null : null,
              needs_input_title: needsInput ? update.title || null : null,
              needs_input_message: needsInput ? update.message || null : null,
              needs_input_detected_at: needsInput ? update.detectedAt || null : null,
            }
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
        const activityAt = new Date().toISOString()
        setState(s => {
          const ptyOutput = new Map(s.ptyOutput)
          const chunks = ptyOutput.get(sessionId) || []
          ptyOutput.set(sessionId, [...chunks, msg.data as string])
          const sessions = updateSession(s.sessions, sessionId, session => ({
            ...session,
            agent_state: session.needs_input ? 'blocked' : 'working',
            last_activity_at: activityAt,
            done_since: null,
          }))
          return { ...s, sessions, ptyOutput }
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
      case 'session.resumed':
      case 'session.renamed':
      case 'session.updated': {
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
        updateSessionInputRequired(sessionId, true, {
          reason: msg.reason || 'Human input required',
          kind: normalizeInputRequiredKind(msg.kind),
          source: typeof msg.source === 'string' ? msg.source : null,
          title: typeof msg.title === 'string' ? msg.title : null,
          message: typeof msg.message === 'string' ? msg.message : null,
          detectedAt: typeof msg.detectedAt === 'string' ? msg.detectedAt : null,
        })
        break
      }

      case 'session.input_resolved': {
        if (!sessionId) return
        updateSessionInputRequired(sessionId, false)
        break
      }

      case 'session.image.sent': {
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

      case 'error': {
        const requestType = typeof msg.requestType === 'string' ? msg.requestType : null
        const rawMessage = typeof msg.message === 'string' && msg.message.trim()
          ? msg.message.trim()
          : 'Unknown error'
        const message = requestType === 'pty.create'
          ? `Could not create session: ${rawMessage}`
          : rawMessage
        setState(s => ({
          ...s,
          lastError: {
            message,
            requestType,
            daemonId: typeof daemonId === 'string' ? daemonId : null,
          },
        }))
        break
      }
    }
  }, [updateSessionInputRequired, updateSessionStatus])

  useEffect(() => {
    if (!enabled) return
    const interval = setInterval(() => {
      setState(s => ({ ...s, sessions: refreshAgentStates(s.sessions) }))
    }, 5000)
    return () => clearInterval(interval)
  }, [enabled])

  useEffect(() => {
    if (!enabled) {
      wsRef.current?.close()
      return
    }
    let disposed = false

    async function connect() {
      if (disposed) return
      await ensureUiTokenCookie()
      if (disposed) return
      const wsUrl = uiWebSocketUrl('/ws')
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
        setTimeout(() => { void connect() }, 2000)
      }

      ws.onmessage = (event) => {
        if (disposed) return
        const msg = JSON.parse(event.data) as ServerMessage
        handleMessage(msg)
      }
    }

    void connect()

    const interval = setInterval(fetchDaemons, 3000)

    return () => {
      disposed = true
      clearInterval(interval)
      wsRef.current?.close()
    }
  }, [enabled, fetchDaemons, handleMessage])

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
    tool: string = 'codex',
    launch: LaunchOptions = { launchMode: 'local' },
    worktree?: WorktreeOptions,
    label?: string | null,
    cols: number = 120,
    rows: number = 40,
  ) => {
    setState(s => ({ ...s, lastError: null }))
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
      worktree,
      label,
    })
  }, [send])

  const sendPtyInput = useCallback((daemonId: string, sessionId: string, data: string) => {
    send({ type: 'pty.input', daemonId, sessionId, data })
    if (data) updateSessionInputRequired(sessionId, false)
  }, [send, updateSessionInputRequired])

  const sendSessionImage = useCallback((
    daemonId: string,
    sessionId: string,
    image: SessionImagePayload,
  ) => {
    send({
      type: 'session.image.send',
      daemonId,
      sessionId,
      filename: image.filename,
      mimeType: image.mimeType,
      dataBase64: image.dataBase64,
      prompt: image.prompt,
    })
  }, [send])

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

  const renameSession = useCallback((daemonId: string, sessionId: string, label: string | null) => {
    send({ type: 'session.rename', daemonId, sessionId, label })
  }, [send])

  const markSessionSeen = useCallback((daemonId: string, sessionId: string) => {
    const seenAt = new Date().toISOString()
    setState(s => ({
      ...s,
      sessions: updateSession(s.sessions, sessionId, session => normalizeSeenSession({
        ...session,
        last_seen_at: seenAt,
        done_since: null,
      })),
    }))
    send({ type: 'session.mark_seen', daemonId, sessionId })
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

  const dismissError = useCallback(() => {
    setState(s => ({ ...s, lastError: null }))
  }, [])

  return {
    ...state,
    createPtySession,
    sendPtyInput,
    sendSessionImage,
    resizePty,
    stopSession,
    removeSession,
    pauseSession,
    resumeSession,
    renameSession,
    markSessionSeen,
    pauseDaemon,
    resumeDaemon,
    listSessions,
    subscribeSession,
    fetchDaemons,
    dismissError,
  }
}

function normalizeSession(session: SessionInfo): SessionInfo {
  return {
    ...session,
    mode: 'pty',
    label: typeof session.label === 'string' && session.label.trim() ? session.label.trim() : null,
    agent_state: normalizeAgentState(session.agent_state, session),
    last_activity_at: normalizeTimestamp(session.last_activity_at),
    last_seen_at: normalizeTimestamp(session.last_seen_at),
    done_since: normalizeTimestamp(session.done_since),
    needs_input: Boolean(session.needs_input),
    needs_input_reason: session.needs_input_reason || null,
    needs_input_kind: normalizeInputRequiredKind(session.needs_input_kind),
    needs_input_source: typeof session.needs_input_source === 'string' ? session.needs_input_source : null,
    needs_input_title: typeof session.needs_input_title === 'string' ? session.needs_input_title : null,
    needs_input_message: typeof session.needs_input_message === 'string' ? session.needs_input_message : null,
    needs_input_detected_at: typeof session.needs_input_detected_at === 'string' ? session.needs_input_detected_at : null,
    launch_mode: session.launch_mode === 'custom' ? 'custom' : 'local',
    launch_command: typeof session.launch_command === 'string' ? session.launch_command : null,
    launch_label: typeof session.launch_label === 'string' ? session.launch_label : null,
    worktree: normalizeWorktree(session.worktree),
    git: normalizeGit(session.git),
  }
}

function upsertSession(list: SessionInfo[], session: SessionInfo): SessionInfo[] {
  if (list.some(s => s.id === session.id)) {
    return list.map(s => s.id === session.id ? session : s)
  }
  return [...list, session]
}

function normalizeInputRequiredKind(kind: unknown): InputRequiredKind | null {
  if (kind === 'permission' || kind === 'confirmation' || kind === 'auth' || kind === 'prompt') {
    return kind
  }
  return null
}

function normalizeAgentState(state: unknown, session: Partial<SessionInfo>): AgentState {
  if (session.needs_input) return 'blocked'
  if (state === 'blocked' || state === 'working' || state === 'done' || state === 'idle' || state === 'unknown') {
    return state
  }
  if (session.status === 'running') return 'idle'
  return 'unknown'
}

function normalizeTimestamp(value: unknown): string | null {
  if (typeof value !== 'string' || !value.trim()) return null
  const time = Date.parse(value)
  if (Number.isNaN(time)) return null
  return new Date(time).toISOString()
}

function normalizeWorktree(worktree: unknown): SessionWorktreeInfo | null {
  if (!worktree || typeof worktree !== 'object') return null
  const candidate = worktree as Record<string, unknown>
  if (
    typeof candidate.source_dir !== 'string'
    || typeof candidate.repo_root !== 'string'
    || typeof candidate.worktree_root !== 'string'
    || typeof candidate.branch !== 'string'
  ) {
    return null
  }
  return {
    source_dir: candidate.source_dir,
    repo_root: candidate.repo_root,
    worktree_root: candidate.worktree_root,
    branch: candidate.branch,
    start_point: typeof candidate.start_point === 'string' ? candidate.start_point : 'HEAD',
  }
}

function normalizeGit(git: unknown): SessionGitInfo | null {
  if (!git || typeof git !== 'object') return null
  const candidate = git as Record<string, unknown>
  if (typeof candidate.repo_root !== 'string') return null
  return {
    branch: typeof candidate.branch === 'string' && candidate.branch ? candidate.branch : null,
    dirty: Boolean(candidate.dirty),
    ahead: typeof candidate.ahead === 'number' ? candidate.ahead : null,
    behind: typeof candidate.behind === 'number' ? candidate.behind : null,
    is_worktree: Boolean(candidate.is_worktree),
    repo_root: candidate.repo_root,
  }
}

function updateSession(
  sessions: Map<string, SessionInfo[]>,
  sessionId: string,
  updater: (session: SessionInfo) => SessionInfo,
): Map<string, SessionInfo[]> {
  const next = new Map(sessions)
  for (const [daemonId, list] of next) {
    next.set(daemonId, list.map(session => session.id === sessionId ? updater(session) : session))
  }
  return next
}

function refreshAgentStates(sessions: Map<string, SessionInfo[]>): Map<string, SessionInfo[]> {
  let changed = false
  const next = new Map<string, SessionInfo[]>()
  for (const [daemonId, list] of sessions) {
    const updated = list.map(session => {
      const refreshed = refreshAgentState(session)
      changed = changed || refreshed !== session
      return refreshed
    })
    next.set(daemonId, updated)
  }
  return changed ? next : sessions
}

function refreshAgentState(session: SessionInfo): SessionInfo {
  if (session.needs_input) {
    return session.agent_state === 'blocked' ? session : { ...session, agent_state: 'blocked' }
  }
  const activityTime = session.last_activity_at ? Date.parse(session.last_activity_at) : NaN
  if (Number.isNaN(activityTime)) {
    const idleState: AgentState = session.status === 'running' || session.status === 'paused' || session.status === 'stopped'
      ? 'idle'
      : 'unknown'
    return session.agent_state === idleState ? session : { ...session, agent_state: idleState }
  }
  const seenTime = session.last_seen_at ? Date.parse(session.last_seen_at) : NaN
  const unseen = Number.isNaN(seenTime) || seenTime < activityTime
  const recent = Date.now() - activityTime <= AGENT_WORKING_WINDOW_MS
  let agentState: AgentState = 'idle'
  let doneSince = session.done_since
  if (session.status === 'running' && recent) {
    agentState = 'working'
    doneSince = null
  } else if (unseen) {
    agentState = 'done'
    doneSince = doneSince || session.last_activity_at
  }
  if (session.agent_state === agentState && session.done_since === doneSince) return session
  return { ...session, agent_state: agentState, done_since: doneSince }
}

function normalizeSeenSession(session: SessionInfo): SessionInfo {
  if (session.needs_input) return { ...session, agent_state: 'blocked' }
  if (session.status === 'running' && session.last_activity_at) {
    const activityTime = Date.parse(session.last_activity_at)
    if (!Number.isNaN(activityTime) && Date.now() - activityTime <= AGENT_WORKING_WINDOW_MS) {
      return { ...session, agent_state: 'working', done_since: null }
    }
  }
  return { ...session, agent_state: session.status === 'running' || session.status === 'paused' || session.status === 'stopped' ? 'idle' : 'unknown', done_since: null }
}
