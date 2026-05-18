import { useEffect, useState } from 'react'
import type { Daemon, SessionInfo } from '../hooks/useAgentUi'

interface Props {
  daemons: Daemon[]
  sessions: Map<string, SessionInfo[]>
  selectedSession: { daemonId: string; sessionId: string } | null
  onSelectSession: (daemonId: string, sessionId: string) => void
  onNewSession: (daemons: Daemon[]) => void
  onCloseSession: (daemonId: string, sessionId: string) => void
  onPauseSession: (daemonId: string, sessionId: string) => void
  onResumeSession: (daemonId: string, sessionId: string) => void
  onRenameSession: (daemonId: string, sessionId: string, label: string | null) => void
  onDuplicateSession: (daemonId: string, session: SessionInfo) => void
}

interface ContextMenuState {
  daemonId: string
  sessionId: string
  x: number
  y: number
}

type EnvironmentKey = 'local' | 'remote' | 'docker'

interface GroupedSession {
  daemon: Daemon
  session: SessionInfo
}

interface ProjectGroup {
  name: string
  daemons: Map<string, Daemon>
  sessions: GroupedSession[]
}

interface EnvironmentGroup {
  key: EnvironmentKey
  label: string
  projects: Map<string, ProjectGroup>
}

const ENVIRONMENT_LABELS: Record<EnvironmentKey, string> = {
  local: 'Local',
  remote: 'Remote',
  docker: 'Docker',
}

const ENVIRONMENT_ORDER: EnvironmentKey[] = ['local', 'remote', 'docker']

export function DaemonList({
  daemons,
  sessions,
  selectedSession,
  onSelectSession,
  onNewSession,
  onCloseSession,
  onPauseSession,
  onResumeSession,
  onRenameSession,
  onDuplicateSession,
}: Props) {
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null)
  const [copiedPathSessionId, setCopiedPathSessionId] = useState<string | null>(null)
  const groupedDaemons = groupDaemons(daemons, sessions)
  const contextSession = contextMenu ? findSession(sessions, contextMenu.daemonId, contextMenu.sessionId) : null

  useEffect(() => {
    if (!contextMenu) return
    const close = () => setContextMenu(null)
    window.addEventListener('click', close)
    window.addEventListener('contextmenu', close)
    return () => {
      window.removeEventListener('click', close)
      window.removeEventListener('contextmenu', close)
    }
  }, [contextMenu])

  return (
    <div className="daemon-list">
      <div className="daemon-list-header">
        <h2>Agent hosts</h2>
      </div>
      {daemons.length === 0 && (
        <div className="daemon-list-empty">No agent hosts connected</div>
      )}
      {groupedDaemons.map(environment => (
        <div key={environment.key} className="environment-group">
          <div className="environment-header">
            <span>{environment.label}</span>
            {countEnvironmentAttention(environment) > 0 && (
              <span className="group-input-count" title="Sessions needing attention">
                {countEnvironmentAttention(environment)}
              </span>
            )}
            <EnvironmentNewSessionButton environment={environment} onNewSession={onNewSession} />
          </div>
          {[...environment.projects.values()].map(project => (
            <div key={`${environment.key}-${project.name}`} className="project-group">
              <div className="project-header">
                <span className="project-name">{project.name}</span>
                {countProjectAttention(project) > 0 && (
                  <span className="group-input-count" title="Sessions needing attention">
                    {countProjectAttention(project)}
                  </span>
                )}
                <span className="project-count">{countProjectSessions(project)}</span>
              </div>
              <ProjectSection
                project={project}
                selectedSession={selectedSession}
                onSelectSession={onSelectSession}
                onPauseSession={onPauseSession}
                onResumeSession={onResumeSession}
                onOpenContextMenu={state => {
                  setCopiedPathSessionId(null)
                  setContextMenu(state)
                }}
              />
            </div>
          ))}
        </div>
      ))}
      {contextMenu && (
        <div
          className="session-context-menu"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onClick={event => event.stopPropagation()}
        >
          <button
            type="button"
            disabled={!contextSession}
            onClick={() => {
              if (!contextSession) return
              const nextLabel = window.prompt('Session name', contextSession.label || projectNameForSession(contextSession))
              if (nextLabel === null) return
              onRenameSession(contextMenu.daemonId, contextMenu.sessionId, nextLabel.trim() || null)
              setContextMenu(null)
            }}
          >
            Rename
          </button>
          <button
            type="button"
            disabled={!contextSession}
            onClick={() => {
              if (!contextSession) return
              onDuplicateSession(contextMenu.daemonId, contextSession)
              setContextMenu(null)
            }}
          >
            Duplicate
          </button>
          <button
            type="button"
            disabled={!contextSession}
            onClick={() => {
              if (!contextSession) return
              void copyText(contextSession.work_dir)
              setCopiedPathSessionId(contextSession.id)
            }}
          >
            {copiedPathSessionId === contextSession?.id ? 'Copied path' : 'Copy path'}
          </button>
          <button
            type="button"
            className="danger"
            onClick={() => {
              onCloseSession(contextMenu.daemonId, contextMenu.sessionId)
              setContextMenu(null)
            }}
          >
            Close
          </button>
        </div>
      )}
    </div>
  )
}

function EnvironmentNewSessionButton({
  environment,
  onNewSession,
}: {
  environment: EnvironmentGroup
  onNewSession: (daemons: Daemon[]) => void
}) {
  const daemons = environmentDaemons(environment).filter(daemon => daemon.connected)
  const disabled = daemons.length === 0

  return (
    <button
      className="btn-icon environment-action"
      disabled={disabled}
      onClick={() => onNewSession(daemons)}
      title={disabled ? `No connected agent hosts in ${environment.label}` : `New session on ${environment.label} agent host`}
    >
      +
    </button>
  )
}

function ProjectSection({
  project,
  selectedSession,
  onSelectSession,
  onPauseSession,
  onResumeSession,
  onOpenContextMenu,
}: {
  project: ProjectGroup
  selectedSession: { daemonId: string; sessionId: string } | null
  onSelectSession: (daemonId: string, sessionId: string) => void
  onPauseSession: (daemonId: string, sessionId: string) => void
  onResumeSession: (daemonId: string, sessionId: string) => void
  onOpenContextMenu: (state: ContextMenuState) => void
}) {
  return (
    <div className="project-sessions">
      {project.sessions.length === 0 && (
        <div className="session-item empty-session">
          <span>No active sessions</span>
        </div>
      )}
      {project.sessions.map(({ daemon, session }) => (
        <div
          key={`${daemon.id}-${session.id}`}
          className={`session-item ${selectedSession?.daemonId === daemon.id && selectedSession?.sessionId === session.id ? 'selected' : ''} ${session.needs_input ? 'needs-input' : ''} ${session.agent_state === 'done' ? 'needs-review' : ''}`}
          onClick={() => onSelectSession(daemon.id, session.id)}
          onContextMenu={event => {
            event.preventDefault()
            event.stopPropagation()
            onOpenContextMenu({
              daemonId: daemon.id,
              sessionId: session.id,
              x: event.clientX,
              y: event.clientY,
            })
          }}
          title={session.needs_input ? session.needs_input_reason || 'Human input required' : daemon.name}
          aria-label={session.needs_input ? `${session.tool} session needs input` : `${session.tool} session`}
        >
          <span className={`status-dot ${statusClass(session)}`} />
          {session.needs_input && (
            <span className={`input-required-badge ${session.needs_input_kind || 'prompt'}`}>
              {inputBadgeLabel(session.needs_input_kind)}
            </span>
          )}
          <span className={`tool-badge ${session.tool || 'codex'}`}>{session.tool || 'codex'}</span>
          {session.launch_mode === 'custom' && (
            <span className="launch-badge" title={session.launch_command || 'Custom launch'}>
              {session.launch_label || 'custom'}
            </span>
          )}
          <GitBadges session={session} />
          <span className="session-dir" title={session.work_dir}>{session.label || session.work_dir}</span>
          {project.daemons.size > 1 && (
            <span className="session-daemon" title={daemon.hostname || daemon.host}>{daemon.name}</span>
          )}
          {session.status === 'paused' ? (
            <button
              className="btn-icon session-action"
              onClick={e => {
                e.stopPropagation()
                onResumeSession(daemon.id, session.id)
              }}
              title="Resume session"
            >
              &gt;
            </button>
          ) : (
            <button
              className="btn-icon session-action"
              onClick={e => {
                e.stopPropagation()
                onPauseSession(daemon.id, session.id)
              }}
              title="Pause session"
            >
              ||
            </button>
          )}
          </div>
      ))}
    </div>
  )
}

function groupDaemons(daemons: Daemon[], sessions: Map<string, SessionInfo[]>): EnvironmentGroup[] {
  const groups = new Map<EnvironmentKey, EnvironmentGroup>()

  for (const key of ENVIRONMENT_ORDER) {
    groups.set(key, {
      key,
      label: ENVIRONMENT_LABELS[key],
      projects: new Map(),
    })
  }

  for (const daemon of daemons) {
    const environment = deriveEnvironment(daemon)
    const daemonSessions = sessions.get(daemon.id) || []

    if (daemonSessions.length === 0) {
      addDaemonToProject(groups.get(environment)!, 'No project', daemon)
      continue
    }

    for (const session of daemonSessions) {
      addSessionToProject(groups.get(environment)!, projectNameForSession(session), daemon, session)
    }
  }

  return ENVIRONMENT_ORDER
    .map(key => groups.get(key)!)
    .filter(group => group.projects.size > 0)
}

function addDaemonToProject(
  environment: EnvironmentGroup,
  projectName: string,
  daemon: Daemon,
) {
  let project = environment.projects.get(projectName)
  if (!project) {
    project = { name: projectName, daemons: new Map(), sessions: [] }
    environment.projects.set(projectName, project)
  }

  project.daemons.set(daemon.id, daemon)
}

function addSessionToProject(
  environment: EnvironmentGroup,
  projectName: string,
  daemon: Daemon,
  session: SessionInfo,
) {
  addDaemonToProject(environment, projectName, daemon)
  environment.projects.get(projectName)!.sessions.push({ daemon, session })
}

function deriveEnvironment(daemon: Daemon): EnvironmentKey {
  const fields = [daemon.name, daemon.host, daemon.hostname].map(value => value.toLowerCase())
  if (fields.some(value => value.includes('docker') || value.includes('container'))) {
    return 'docker'
  }
  if (isLocalHost(daemon.host) || isLocalHost(daemon.hostname)) {
    return 'local'
  }
  if (daemon.hostname && daemon.hostname === window.location.hostname) {
    return 'local'
  }
  return 'remote'
}

function isLocalHost(value: string): boolean {
  const normalized = value.toLowerCase()
  return normalized === 'localhost'
    || normalized === '0.0.0.0'
    || normalized === '::'
    || normalized === '::1'
    || normalized.startsWith('127.')
}

function projectNameFromPath(path: string): string {
  const trimmed = path.trim().replace(/[\\/]+$/, '')
  if (!trimmed || trimmed === '~') return 'Home'
  const parts = trimmed.split(/[\\/]+/)
  return parts[parts.length - 1] || trimmed
}

function projectNameForSession(session: SessionInfo): string {
  return projectNameFromPath(session.worktree?.source_dir || session.work_dir)
}

function countProjectSessions(project: ProjectGroup): number {
  return project.sessions.length
}

function countProjectAttention(project: ProjectGroup): number {
  return project.sessions.filter(({ session }) => session.needs_input || session.agent_state === 'done').length
}

function countEnvironmentAttention(environment: EnvironmentGroup): number {
  return [...environment.projects.values()]
    .reduce((total, project) => total + countProjectAttention(project), 0)
}

function inputBadgeLabel(kind: SessionInfo['needs_input_kind']): string {
  if (kind === 'permission') return 'Permit'
  if (kind === 'confirmation') return 'Confirm'
  if (kind === 'auth') return 'Auth'
  return 'Input'
}

function environmentDaemons(environment: EnvironmentGroup): Daemon[] {
  const daemons = new Map<string, Daemon>()
  for (const project of environment.projects.values()) {
    for (const daemon of project.daemons.values()) {
      daemons.set(daemon.id, daemon)
    }
  }
  return [...daemons.values()]
}

function statusClass(session: SessionInfo): string {
  if (session.needs_input || session.agent_state === 'blocked') return 'blocked'
  if (session.agent_state === 'working') return 'working'
  if (session.agent_state === 'done') return 'done'
  if (session.agent_state === 'idle') return 'idle'
  return session.status || 'unknown'
}

function GitBadges({ session }: { session: SessionInfo }) {
  const git = session.git
  if (!git?.branch && !session.worktree) return null
  return (
    <span className="session-git-badges" aria-label="Git status">
      {session.worktree && (
        <span className="git-badge worktree" title={`Worktree branch ${session.worktree.branch}`}>
          wt
        </span>
      )}
      {git?.branch && (
        <span className="git-badge branch" title={`Git branch ${git.branch}`}>
          {git.branch}
        </span>
      )}
      {git?.dirty && (
        <span className="git-badge dirty" title="Uncommitted changes">
          *
        </span>
      )}
      {typeof git?.ahead === 'number' && git.ahead > 0 && (
        <span className="git-badge" title={`${git.ahead} commits ahead`}>
          +{git.ahead}
        </span>
      )}
      {typeof git?.behind === 'number' && git.behind > 0 && (
        <span className="git-badge" title={`${git.behind} commits behind`}>
          -{git.behind}
        </span>
      )}
    </span>
  )
}

function findSession(
  sessions: Map<string, SessionInfo[]>,
  daemonId: string,
  sessionId: string,
): SessionInfo | null {
  return (sessions.get(daemonId) || []).find(session => session.id === sessionId) || null
}

async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.append(textarea)
    textarea.select()
    document.execCommand('copy')
    textarea.remove()
  }
}
