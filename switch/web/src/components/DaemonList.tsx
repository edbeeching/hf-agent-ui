import type { Daemon, SessionInfo } from '../hooks/useSwitch'

interface Props {
  daemons: Daemon[]
  sessions: Map<string, SessionInfo[]>
  selectedSession: { daemonId: string; sessionId: string } | null
  onSelectSession: (daemonId: string, sessionId: string) => void
  onNewSession: (daemonId: string) => void
}

export function DaemonList({ daemons, sessions, selectedSession, onSelectSession, onNewSession }: Props) {
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
                title={session.needs_input ? session.needs_input_reason || 'Human input required' : undefined}
              >
                <span className={`status-dot ${session.status}`} />
                {session.needs_input && <span className="input-required-badge">!</span>}
                <span className={`tool-badge ${session.tool || 'claude'}`}>{session.tool || 'claude'}</span>
                {session.mode === 'pty' && <span className="mode-badge">tty</span>}
                <span className="session-dir">{session.work_dir}</span>
              </div>
            ))}
          </div>
        )
      })}
    </div>
  )
}
