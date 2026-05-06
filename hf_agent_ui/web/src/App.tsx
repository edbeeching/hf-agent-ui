import { useEffect, useState } from 'react'
import { useAgentUi } from './hooks/useAgentUi'
import type { Daemon } from './hooks/useAgentUi'
import { DaemonList } from './components/DaemonList'
import { TerminalView } from './components/TerminalView'
import { NewSessionDialog } from './components/NewSessionDialog'
import { uiAuthFetch } from './auth'
import './App.css'

const SELECTED_SESSION_STORAGE_KEY = 'hf-agent-ui.selectedSession'
const RECENT_WORK_DIRS_STORAGE_KEY = 'hf-agent-ui.recentWorkDirs'
const MAX_RECENT_WORK_DIRS = 8
const SHOW_CLOUD_HOSTS = false
type MobileView = 'terminal' | 'sessions' | 'connect'

function App() {
  const sw = useAgentUi()
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
  const [newSessionDaemonIds, setNewSessionDaemonIds] = useState<string[] | null>(null)
  const [recentWorkDirs, setRecentWorkDirs] = useState<string[]>(() => readRecentWorkDirs())
  const [activeMobileView, setActiveMobileView] = useState<MobileView>('terminal')
  const activeSelected = selected && daemons.some(daemon => daemon.id === selected.daemonId)
    && (sessions.get(selected.daemonId) || []).some(session => session.id === selected.sessionId)
    ? selected
    : null
  const activeSession = activeSelected
    ? (sessions.get(activeSelected.daemonId) || []).find(session => session.id === activeSelected.sessionId) || null
    : null
  const inputRequiredCount = [...sessions.values()]
    .flat()
    .filter(session => session.needs_input).length

  const selectedPtyOutput = activeSelected ? ptyOutput.get(activeSelected.sessionId) || [] : []
  const newSessionDaemons = newSessionDaemonIds
    ? newSessionDaemonIds.map(id => daemons.find(daemon => daemon.id === id)).filter((daemon): daemon is Daemon => Boolean(daemon))
    : []

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

  useEffect(() => {
    document.title = inputRequiredCount > 0 ? `(${inputRequiredCount}) hf-agent-ui` : 'hf-agent-ui'
    return () => {
      document.title = 'hf-agent-ui'
    }
  }, [inputRequiredCount])

  return (
    <div className="app">
      <aside className={`sidebar ${activeMobileView === 'sessions' ? 'mobile-active' : ''}`}>
        <div className="sidebar-title">
          <h1>hf-agent-ui</h1>
          <span className={`connection-badge ${connected ? 'connected' : ''}`}>
            {connected ? 'Connected' : 'Disconnected'}
          </span>
        </div>
        <DaemonList
          daemons={daemons}
          sessions={sessions}
          selectedSession={activeSelected}
          onSelectSession={(daemonId, sessionId) => {
            setSelected({ daemonId, sessionId })
            setActiveMobileView('terminal')
          }}
          onNewSession={daemons => setNewSessionDaemonIds(daemons.map(daemon => daemon.id))}
          onCloseSession={(daemonId, sessionId) => {
            removeSession(daemonId, sessionId)
            if (selected?.sessionId === sessionId) {
              setSelected(null)
            }
          }}
          onPauseSession={(daemonId, sessionId) => sw.pauseSession(daemonId, sessionId)}
          onResumeSession={(daemonId, sessionId) => sw.resumeSession(daemonId, sessionId)}
        />
        <ConnectDaemonPanel daemons={daemons} />
      </aside>

      <main className={`main-panel ${activeMobileView === 'terminal' ? 'mobile-active' : ''}`}>
        <TerminalView
          sessionId={activeSelected?.sessionId || ''}
          output={selectedPtyOutput}
          visible={activeMobileView === 'terminal'}
          needsInput={Boolean(activeSession?.needs_input)}
          inputReason={activeSession?.needs_input_reason || null}
          tool={activeSession?.tool}
          onInput={data => {
            if (activeSelected) sendPtyInput(activeSelected.daemonId, activeSelected.sessionId, data)
          }}
          onResize={(cols, rows) => {
            if (activeSelected) resizePty(activeSelected.daemonId, activeSelected.sessionId, cols, rows)
          }}
        />
      </main>

      <section className={`mobile-connect-panel ${activeMobileView === 'connect' ? 'mobile-active' : ''}`}>
        <ConnectDaemonPanel daemons={daemons} />
      </section>

      <nav className="mobile-tabbar" aria-label="Mobile navigation">
        <button
          type="button"
          className={activeMobileView === 'terminal' ? 'active' : ''}
          aria-current={activeMobileView === 'terminal' ? 'page' : undefined}
          onClick={() => setActiveMobileView('terminal')}
        >
          Terminal
        </button>
        <button
          type="button"
          className={activeMobileView === 'sessions' ? 'active' : ''}
          aria-current={activeMobileView === 'sessions' ? 'page' : undefined}
          onClick={() => setActiveMobileView('sessions')}
        >
          {inputRequiredCount > 0 ? `Sessions (${inputRequiredCount})` : 'Sessions'}
        </button>
        <button
          type="button"
          className={activeMobileView === 'connect' ? 'active' : ''}
          aria-current={activeMobileView === 'connect' ? 'page' : undefined}
          onClick={() => setActiveMobileView('connect')}
        >
          Connect
        </button>
      </nav>

      {newSessionDaemons.length > 0 && (
        <NewSessionDialog
          daemons={newSessionDaemons}
          recentWorkDirs={recentWorkDirs}
          onClose={() => setNewSessionDaemonIds(null)}
          onCreate={(daemonId, workDir, tool, launch) => {
            setRecentWorkDirs(updateRecentWorkDirs(workDir))
            createPtySession(daemonId, workDir, tool, launch)
            setActiveMobileView('terminal')
          }}
        />
      )}
    </div>
  )
}

export default App

function ConnectDaemonPanel({ daemons }: { daemons: Daemon[] }) {
  const [copied, setCopied] = useState<string | null>(null)
  const [hostHubUrl, setDaemonHubUrl] = useState(window.location.origin)
  const [hostTokenRequired, setDaemonTokenRequired] = useState(false)
  const [hostToken, setDaemonToken] = useState<string | null>(null)
  const [installCommand, setInstallCommand] = useState(DEFAULT_INSTALL_COMMAND)
  const daemonCommand = daemonLaunchCommand(hostHubUrl, hostTokenRequired, hostToken)

  useEffect(() => {
    let disposed = false
    async function fetchHubInfo() {
      try {
        const res = await uiAuthFetch('/api/hub')
        const info = await res.json() as {
          hostHubUrl?: unknown
          hostTokenRequired?: unknown
          hostToken?: unknown
          installCommand?: unknown
        }
        if (!disposed && typeof info.hostHubUrl === 'string' && info.hostHubUrl.trim()) {
          setDaemonHubUrl(info.hostHubUrl)
        }
        if (!disposed) {
          setDaemonTokenRequired(Boolean(info.hostTokenRequired))
          setDaemonToken(typeof info.hostToken === 'string' && info.hostToken ? info.hostToken : null)
          setInstallCommand(typeof info.installCommand === 'string' && info.installCommand ? info.installCommand : DEFAULT_INSTALL_COMMAND)
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
      <div className="connect-panel-title">Connect an agent host</div>
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
      <button
        type="button"
        className="update-button"
        disabled
        title="Update from the Space UI will be enabled after the GitHub repo is public."
      >
        Update unavailable
      </button>
      {SHOW_CLOUD_HOSTS && <HfCloudHostPanel daemons={daemons} />}
    </div>
  )
}

const DEFAULT_INSTALL_COMMAND = 'uv -vv tool install --force --reinstall git+https://github.com/edbeeching/hf-agent-ui.git'

interface HfCloudConfig {
  enabled: boolean
  missingConfig: string[]
  defaults: {
    image: string
    flavor: string
    timeout: string
    spaceRepoId: string
    namespace: string | null
  }
}

interface HfHardware {
  name: string
  prettyName: string
  cpu: string | null
  ram: string | null
  unitCostUsd: number | null
  unitLabel: string | null
  accelerator: {
    type: string | null
    model: string | null
    quantity: string | null
    vram: string | null
    manufacturer: string | null
  } | null
}

interface HfCloudJob {
  id: string
  url: string | null
  stage: string
  message: string | null
  createdAt: string | null
  image: string | null
  flavor: string | null
  daemonName: string | null
}

function HfCloudHostPanel({ daemons }: { daemons: Daemon[] }) {
  const [config, setConfig] = useState<HfCloudConfig | null>(null)
  const [hardware, setHardware] = useState<HfHardware[]>([])
  const [jobs, setJobs] = useState<HfCloudJob[]>([])
  const [image, setImage] = useState('python:3.12')
  const [flavor, setFlavor] = useState('cpu-basic')
  const [timeout, setTimeoutValue] = useState('2h')
  const [name, setName] = useState('')
  const [status, setStatus] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let disposed = false

    async function loadConfig() {
      try {
        const res = await uiAuthFetch('/api/cloud/hf/config')
        const payload = await res.json() as HfCloudConfig
        if (disposed) return
        setConfig(payload)
        setImage(payload.defaults.image)
        setFlavor(payload.defaults.flavor)
        setTimeoutValue(payload.defaults.timeout)
      } catch {
        if (!disposed) setStatus('HF Jobs config unavailable')
      }
    }

    loadConfig()
    return () => {
      disposed = true
    }
  }, [])

  useEffect(() => {
    if (!config?.enabled) return
    let disposed = false

    async function loadHardware() {
      try {
        const res = await uiAuthFetch('/api/cloud/hf/hardware')
        if (!res.ok) throw new Error(await errorText(res))
        const payload = await res.json() as HfHardware[]
        if (!disposed) setHardware(payload)
      } catch {
        if (!disposed) setHardware([])
      }
    }

    loadHardware()
    return () => {
      disposed = true
    }
  }, [config?.enabled])

  useEffect(() => {
    if (!config?.enabled) return
    let disposed = false

    async function loadJobs() {
      try {
        const res = await uiAuthFetch('/api/cloud/hf/jobs')
        if (!res.ok) throw new Error(await errorText(res))
        const payload = await res.json() as HfCloudJob[]
        if (!disposed) setJobs(payload)
      } catch {
        if (!disposed) setStatus('HF Jobs status unavailable')
      }
    }

    loadJobs()
    const interval = window.setInterval(loadJobs, 5000)
    return () => {
      disposed = true
      window.clearInterval(interval)
    }
  }, [config?.enabled])

  async function launchJob() {
    setBusy(true)
    setStatus(null)
    try {
      const res = await uiAuthFetch('/api/cloud/hf/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image,
          flavor,
          timeout,
          name: name.trim() || undefined,
        }),
      })
      if (!res.ok) throw new Error(await errorText(res))
      const job = await res.json() as HfCloudJob
      setJobs(current => [job, ...current.filter(existing => existing.id !== job.id)])
      setStatus(`Launched ${job.id}`)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'HF Jobs launch failed')
    } finally {
      setBusy(false)
    }
  }

  async function cancelJob(jobId: string) {
    setStatus(null)
    try {
      const res = await uiAuthFetch(`/api/cloud/hf/jobs/${encodeURIComponent(jobId)}/cancel`, {
        method: 'POST',
      })
      if (!res.ok) throw new Error(await errorText(res))
      setStatus(`Stopping ${jobId}`)
      setJobs(current => current.map(job => job.id === jobId ? { ...job, stage: 'CANCELLING' } : job))
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'HF Jobs stop failed')
    }
  }

  const enabled = Boolean(config?.enabled)
  const missing = config?.missingConfig || []

  return (
    <div className="cloud-host-panel">
      <div className="connect-panel-title">Cloud host</div>
      {!enabled && (
        <div className="cloud-warning">
          Missing {missing.length ? missing.join(', ') : 'HF Jobs config'}
        </div>
      )}
      <div className="cloud-grid">
        <label>
          <span>Image</span>
          <input value={image} onChange={event => setImage(event.target.value)} disabled={!enabled || busy} />
        </label>
        <label>
          <span>Hardware</span>
          <select value={flavor} onChange={event => setFlavor(event.target.value)} disabled={!enabled || busy}>
            <option value={flavor}>{flavor}</option>
            {hardware
              .filter(item => item.name !== flavor)
              .map(item => (
                <option key={item.name} value={item.name}>
                  {hardwareLabel(item)}
                </option>
              ))}
          </select>
        </label>
        <label>
          <span>Timeout</span>
          <input value={timeout} onChange={event => setTimeoutValue(event.target.value)} disabled={!enabled || busy} />
        </label>
        <label>
          <span>Name</span>
          <input value={name} onChange={event => setName(event.target.value)} placeholder="auto" disabled={!enabled || busy} />
        </label>
      </div>
      <button type="button" className="cloud-primary-button" disabled={!enabled || busy} onClick={launchJob}>
        {busy ? 'Launching...' : 'Launch cloud host'}
      </button>
      {status && <div className="cloud-status">{status}</div>}
      {jobs.length > 0 && (
        <div className="cloud-job-list">
          {jobs.slice(0, 5).map(job => (
            <CloudJobRow key={job.id} job={job} daemons={daemons} onCancel={cancelJob} />
          ))}
        </div>
      )}
    </div>
  )
}

function CloudJobRow({
  job,
  daemons,
  onCancel,
}: {
  job: HfCloudJob
  daemons: Daemon[]
  onCancel: (jobId: string) => void
}) {
  const connected = Boolean(job.daemonName && daemons.some(daemon => daemon.name === job.daemonName && daemon.connected))
  const terminal = ['COMPLETED', 'FAILED', 'CANCELLED', 'TIMEOUT', 'ERROR'].includes(job.stage)
  return (
    <div className="cloud-job-row">
      <div className="cloud-job-main">
        <span className={`cloud-job-dot ${job.stage.toLowerCase()}`} />
        <span className="cloud-job-id" title={job.id}>{job.daemonName || job.id}</span>
        {connected && <span className="cloud-connected">connected</span>}
      </div>
      <div className="cloud-job-meta">
        <span>{job.stage.toLowerCase()}</span>
        {job.flavor && <span>{job.flavor}</span>}
      </div>
      <div className="cloud-job-actions">
        {job.url && (
          <a href={job.url} target="_blank" rel="noreferrer" title="Open HF Job">
            HF
          </a>
        )}
        <button type="button" disabled={terminal} onClick={() => onCancel(job.id)}>
          Stop
        </button>
      </div>
    </div>
  )
}

function hardwareLabel(item: HfHardware): string {
  const accelerator = item.accelerator ? ` · ${item.accelerator.model || item.accelerator.type}` : ''
  return `${item.name}${accelerator}`
}

async function errorText(response: Response): Promise<string> {
  try {
    const data = await response.json() as { detail?: unknown }
    return typeof data.detail === 'string' ? data.detail : response.statusText
  } catch {
    return response.statusText
  }
}

function daemonLaunchCommand(
  hostHubUrl: string,
  hostTokenRequired: boolean,
  hostToken: string | null,
): string {
  const hfTokenArg = isHfSpaceUrl(hostHubUrl) ? ' --hf-token "$HF_TOKEN"' : ''
  if (!hostTokenRequired) {
    return `hf-agent-ui host --hub ${hostHubUrl}${hfTokenArg}`
  }
  if (hostToken) {
    return `hf-agent-ui host --hub ${hostHubUrl} --token ${hostToken}${hfTokenArg}`
  }
  return `hf-agent-ui host --hub ${hostHubUrl} --token <token>${hfTokenArg}`
}

function isHfSpaceUrl(value: string): boolean {
  try {
    return new URL(value).hostname.endsWith('.hf.space')
  } catch {
    return false
  }
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
