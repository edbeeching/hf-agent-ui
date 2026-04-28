import { useEffect, useState } from 'react'
import type { Daemon, SessionInfo } from '../hooks/useSwitch'

interface Props {
  daemons: Daemon[]
  sessions: Map<string, SessionInfo[]>
  selectedSession: { daemonId: string; sessionId: string } | null
  onSelectSession: (daemonId: string, sessionId: string) => void
  onNewSession: (daemonId: string) => void
  onCloseSession: (daemonId: string, sessionId: string) => void
  onPauseSession: (daemonId: string, sessionId: string) => void
  onResumeSession: (daemonId: string, sessionId: string) => void
  onPauseDaemon: (daemonId: string) => void
  onResumeDaemon: (daemonId: string) => void
}

interface ContextMenuState {
  daemonId: string
  sessionId: string
  x: number
  y: number
}

export function DaemonList({
  daemons,
  sessions,
  selectedSession,
  onSelectSession,
  onNewSession,
  onCloseSession,
  onPauseSession,
  onResumeSession,
  onPauseDaemon,
  onResumeDaemon,
}: Props) {
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null)

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
        <h2>Daemons</h2>
      </div>
      {daemons.length === 0 && (
        <div className="daemon-list-empty">No daemons connected</div>
      )}
      {daemons.map(daemon => {
        const daemonSessions = sessions.get(daemon.id) || []
        return (
          <div key={daemon.id} className="daemon-group">
            <div className="daemon-header">
              <span className={`status-dot ${daemon.connected ? 'connected' : 'disconnected'}`} />
              <span className="daemon-name">{daemon.name}</span>
              <span className="daemon-hostname">{daemon.hostname}</span>
              <button
                className="btn-icon"
                onClick={() => onPauseDaemon(daemon.id)}
                title="Pause all sessions"
              >
                ||
              </button>
              <button
                className="btn-icon"
                onClick={() => onResumeDaemon(daemon.id)}
                title="Resume all sessions"
              >
                &gt;
              </button>
              <button
                className="btn-icon"
                onClick={() => onNewSession(daemon.id)}
                title="New session"
              >
                +
              </button>
            </div>
            {daemonSessions.map(session => (
              <div
                key={session.id}
                className={`session-item ${selectedSession?.sessionId === session.id ? 'selected' : ''} ${session.needs_input ? 'needs-input' : ''}`}
                onClick={() => onSelectSession(daemon.id, session.id)}
                onContextMenu={event => {
                  event.preventDefault()
                  event.stopPropagation()
                  setContextMenu({
                    daemonId: daemon.id,
                    sessionId: session.id,
                    x: event.clientX,
                    y: event.clientY,
                  })
                }}
                title={session.needs_input ? session.needs_input_reason || 'Human input required' : undefined}
              >
                <span className={`status-dot ${session.status}`} />
                {session.needs_input && <span className="input-required-badge">!</span>}
                <span className={`tool-badge ${session.tool || 'claude'}`}>{session.tool || 'claude'}</span>
                <span className="session-dir">{session.work_dir}</span>
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
      })}
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
