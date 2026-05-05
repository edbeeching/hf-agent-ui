import { useEffect, useState } from 'react'
import type { Daemon, SessionInfo } from '../hooks/useSwitch'

interface Props {
  daemons: Daemon[]
  sessions: Map<string, SessionInfo[]>
  selectedSession: { daemonId: string; sessionId: string } | null
  onSelectSession: (daemonId: string, sessionId: string) => void
  onNewSession: (daemons: Daemon[]) => void
  onCloseSession: (daemonId: string, sessionId: string) => void
  onPauseSession: (daemonId: string, sessionId: string) => void
  onResumeSession: (daemonId: string, sessionId: string) => void
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
}: Props) {
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null)
  const groupedDaemons = groupDaemons(daemons, sessions)

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
            <EnvironmentNewSessionButton environment={environment} onNewSession={onNewSession} />
          </div>
          {[...environment.projects.values()].map(project => (
            <div key={`${environment.key}-${project.name}`} className="project-group">
              <div className="project-header">
                <span className="project-name">{project.name}</span>
                <span className="project-count">{countProjectSessions(project)}</span>
              </div>
              <ProjectSection
                project={project}
                selectedSession={selectedSession}
                onSelectSession={onSelectSession}
                onPauseSession={onPauseSession}
                onResumeSession={onResumeSession}
                onOpenContextMenu={setContextMenu}
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
          <button type="button" disabled>Rename</button>
          <button type="button" disabled>Duplicate</button>
          <button type="button" disabled>Copy path</button>
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
          className={`session-item ${selectedSession?.daemonId === daemon.id && selectedSession?.sessionId === session.id ? 'selected' : ''} ${session.needs_input ? 'needs-input' : ''}`}
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
        >
          <span className={`status-dot ${session.status}`} />
          {session.needs_input && <span className="input-required-badge">!</span>}
          <span className={`tool-badge ${session.tool || 'claude'}`}>{session.tool || 'claude'}</span>
          {session.launch_mode === 'custom' && (
            <span className="launch-badge" title={session.launch_command || 'Custom launch'}>
              {session.launch_label || 'custom'}
            </span>
          )}
          <span className="session-dir">{session.work_dir}</span>
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
      addSessionToProject(groups.get(environment)!, projectNameFromPath(session.work_dir), daemon, session)
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

function countProjectSessions(project: ProjectGroup): number {
  return project.sessions.length
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
