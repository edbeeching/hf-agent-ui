import { useEffect, useState } from 'react'
import { useSwitch } from './hooks/useSwitch'
import { DaemonList } from './components/DaemonList'
import { TerminalView } from './components/TerminalView'
import { NewSessionDialog } from './components/NewSessionDialog'
import './App.css'

const SELECTED_SESSION_STORAGE_KEY = 'switch.selectedSession'
const RECENT_WORK_DIRS_STORAGE_KEY = 'switch.recentWorkDirs'
const MAX_RECENT_WORK_DIRS = 8

function App() {
  const sw = useSwitch()
  const {
    connected,
    daemons,
    sessions,
    ptyOutput,
    createPtySession,
    sendPtyInput,
    resizePty,
    removeSession,
    listSessions,
    subscribeSession,
  } = sw
  const [selected, setSelected] = useState<{ daemonId: string; sessionId: string } | null>(() => readStoredSelection())
  const [newSessionDaemonId, setNewSessionDaemonId] = useState<string | null>(null)
  const [recentWorkDirs, setRecentWorkDirs] = useState<string[]>(() => readRecentWorkDirs())
  const activeSelected = selected && daemons.some(daemon => daemon.id === selected.daemonId)
    && (sessions.get(selected.daemonId) || []).some(session => session.id === selected.sessionId)
    ? selected
    : null

  const selectedPtyOutput = activeSelected ? ptyOutput.get(activeSelected.sessionId) || [] : []
  const newSessionDaemon = newSessionDaemonId
    ? daemons.find(d => d.id === newSessionDaemonId)
    : null

  useEffect(() => {
    if (!connected) return
    daemons
      .filter(daemon => daemon.connected)
      .forEach(daemon => listSessions(daemon.id))
  }, [connected, daemons, listSessions])

  useEffect(() => {
    if (activeSelected) {
      window.localStorage.setItem(SELECTED_SESSION_STORAGE_KEY, JSON.stringify(activeSelected))
      if (connected) {
        subscribeSession(activeSelected.daemonId, activeSelected.sessionId)
      }
    } else {
      window.localStorage.removeItem(SELECTED_SESSION_STORAGE_KEY)
    }
  }, [activeSelected, connected, subscribeSession])

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="sidebar-title">
          <h1>Switch</h1>
          <span className={`connection-badge ${connected ? 'connected' : ''}`}>
            {connected ? 'Connected' : 'Disconnected'}
          </span>
        </div>
        <DaemonList
          daemons={daemons}
          sessions={sessions}
          selectedSession={activeSelected}
          onSelectSession={(daemonId, sessionId) => setSelected({ daemonId, sessionId })}
          onNewSession={daemonId => setNewSessionDaemonId(daemonId)}
          onCloseSession={(daemonId, sessionId) => {
            removeSession(daemonId, sessionId)
            if (selected?.sessionId === sessionId) {
              setSelected(null)
            }
          }}
          onPauseSession={(daemonId, sessionId) => sw.pauseSession(daemonId, sessionId)}
          onResumeSession={(daemonId, sessionId) => sw.resumeSession(daemonId, sessionId)}
        />
        <ConnectDaemonPanel />
      </aside>

      <main className="main-panel">
        <TerminalView
          sessionId={activeSelected?.sessionId || ''}
          output={selectedPtyOutput}
          onInput={data => {
            if (activeSelected) sendPtyInput(activeSelected.daemonId, activeSelected.sessionId, data)
          }}
          onResize={(cols, rows) => {
            if (activeSelected) resizePty(activeSelected.daemonId, activeSelected.sessionId, cols, rows)
          }}
        />
      </main>

      {newSessionDaemon && (
        <NewSessionDialog
          daemon={newSessionDaemon}
          recentWorkDirs={recentWorkDirs}
          onClose={() => setNewSessionDaemonId(null)}
          onCreate={(daemonId, workDir, tool, launch) => {
            setRecentWorkDirs(updateRecentWorkDirs(workDir))
            createPtySession(daemonId, workDir, tool, launch)
          }}
        />
      )}
    </div>
  )
}

export default App

function ConnectDaemonPanel() {
  const [copied, setCopied] = useState<string | null>(null)
  const [daemonHubUrl, setDaemonHubUrl] = useState(window.location.origin)
  const [daemonTokenRequired, setDaemonTokenRequired] = useState(false)
  const [daemonToken, setDaemonToken] = useState<string | null>(null)
  const installCommand = 'uv -vv tool install --force --reinstall git+ssh://git@github.com/edbeeching/switch.git'
  const daemonCommand = daemonLaunchCommand(daemonHubUrl, daemonTokenRequired, daemonToken)

  useEffect(() => {
    let disposed = false
    async function fetchHubInfo() {
      try {
        const res = await fetch('/api/hub')
        const info = await res.json() as {
          daemonHubUrl?: unknown
          daemonTokenRequired?: unknown
          daemonToken?: unknown
        }
        if (!disposed && typeof info.daemonHubUrl === 'string' && info.daemonHubUrl.trim()) {
          setDaemonHubUrl(info.daemonHubUrl)
        }
        if (!disposed) {
          setDaemonTokenRequired(Boolean(info.daemonTokenRequired))
          setDaemonToken(typeof info.daemonToken === 'string' && info.daemonToken ? info.daemonToken : null)
        }
      } catch {
        // Fall back to the browser URL.
      }
    }
    fetchHubInfo()
    return () => {
      disposed = true
    }
  }, [])

  async function copyCommand(label: string, command: string) {
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(command)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = command
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      textarea.remove()
    }
    setCopied(label)
    window.setTimeout(() => setCopied(current => current === label ? null : current), 1500)
  }

  return (
    <div className="connect-panel">
      <div className="connect-panel-title">Connect a daemon</div>
      <p>Install Switch from the private repo, then launch a daemon with this hub URL. For private Spaces, set HF_TOKEN in the shell first.</p>
      <CommandCopyRow
        label="Install"
        command={installCommand}
        copied={copied === 'install'}
        onCopy={() => copyCommand('install', installCommand)}
      />
      <CommandCopyRow
        label="Launch"
        command={daemonCommand}
        copied={copied === 'launch'}
        onCopy={() => copyCommand('launch', daemonCommand)}
      />
    </div>
  )
}

function daemonLaunchCommand(
  daemonHubUrl: string,
  daemonTokenRequired: boolean,
  daemonToken: string | null,
): string {
  if (!daemonTokenRequired) {
    return `switch daemon --hub ${daemonHubUrl}`
  }
  if (daemonToken) {
    return `switch daemon --hub ${daemonHubUrl} --token ${daemonToken}`
  }
  return `SWITCH_DAEMON_TOKEN=<token> switch daemon --hub ${daemonHubUrl}`
}

function CommandCopyRow({
  label,
  command,
  copied,
  onCopy,
}: {
  label: string
  command: string
  copied: boolean
  onCopy: () => void
}) {
  return (
    <div className="command-copy-row">
      <span className="command-label">{label}</span>
      <code title={command}>{command}</code>
      <button type="button" className="copy-button" onClick={onCopy}>
        {copied ? 'Copied' : 'Copy'}
      </button>
    </div>
  )
}

function readStoredSelection(): { daemonId: string; sessionId: string } | null {
  try {
    const raw = window.localStorage.getItem(SELECTED_SESSION_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as { daemonId?: unknown; sessionId?: unknown }
    if (typeof parsed.daemonId !== 'string' || typeof parsed.sessionId !== 'string') {
      return null
    }
    return { daemonId: parsed.daemonId, sessionId: parsed.sessionId }
  } catch {
    return null
  }
}

function readRecentWorkDirs(): string[] {
  try {
    const raw = window.localStorage.getItem(RECENT_WORK_DIRS_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((entry): entry is string => typeof entry === 'string' && entry.trim() !== '')
      .slice(0, MAX_RECENT_WORK_DIRS)
  } catch {
    return []
  }
}

function updateRecentWorkDirs(workDir: string): string[] {
  const trimmed = workDir.trim()
  const current = readRecentWorkDirs()
  const next = trimmed
    ? [trimmed, ...current.filter(entry => entry !== trimmed)].slice(0, MAX_RECENT_WORK_DIRS)
    : current
  window.localStorage.setItem(RECENT_WORK_DIRS_STORAGE_KEY, JSON.stringify(next))
  return next
}
