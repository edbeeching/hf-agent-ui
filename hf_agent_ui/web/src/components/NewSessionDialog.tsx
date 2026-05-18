import { useState } from 'react'
import type { Daemon, LaunchMode, LaunchOptions, WorktreeOptions } from '../hooks/useAgentUi'

const CUSTOM_LAUNCH_STORAGE_KEY = 'hf-agent-ui.customLaunch'

interface Props {
  daemons: Daemon[]
  getRecentWorkDirs: (daemon: Daemon | null) => string[]
  onRemoveRecentWorkDir: (daemon: Daemon, workDir: string) => void
  onClose: () => void
  onCreate: (
    daemonId: string,
    workDir: string,
    tool: string,
    launch: LaunchOptions,
    worktree?: WorktreeOptions,
  ) => void
}

export function NewSessionDialog({
  daemons,
  getRecentWorkDirs,
  onRemoveRecentWorkDir,
  onClose,
  onCreate,
}: Props) {
  const connectedDaemons = daemons.filter(daemon => daemon.connected)
  const defaultDaemonId = connectedDaemons[0]?.id || ''
  const defaultDaemon = connectedDaemons[0] || null
  const storedCustomLaunch = readCustomLaunch()
  const [daemonId, setDaemonId] = useState(defaultDaemonId)
  const [tool, setTool] = useState('codex')
  const [workDir, setWorkDir] = useState(getRecentWorkDirs(defaultDaemon)[0] || '~')
  const [launchMode, setLaunchMode] = useState<LaunchMode>('local')
  const [launchLabel, setLaunchLabel] = useState(storedCustomLaunch.label)
  const [launchCommand, setLaunchCommand] = useState(storedCustomLaunch.command)
  const [useWorktree, setUseWorktree] = useState(false)
  const [worktreeBranch, setWorktreeBranch] = useState(() => defaultWorktreeBranch('codex'))
  const [worktreeBranchTouched, setWorktreeBranchTouched] = useState(false)
  const [worktreeStartPoint, setWorktreeStartPoint] = useState('HEAD')
  const [error, setError] = useState<string | null>(null)
  const selectedDaemonId = connectedDaemons.some(daemon => daemon.id === daemonId)
    ? daemonId
    : defaultDaemonId
  const selectedDaemon = connectedDaemons.find(daemon => daemon.id === selectedDaemonId) || null
  const recentWorkDirs = getRecentWorkDirs(selectedDaemon)

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!selectedDaemonId) {
      setError('Selected agent host is no longer available.')
      return
    }
    const launch = launchOptions(launchMode, launchLabel, launchCommand)
    if (launch.launchMode === 'custom' && !launch.launchCommand?.includes('{command}')) {
      setError('Custom launch command must include {command}.')
      return
    }
    const worktree = worktreeOptions(useWorktree, workDir, worktreeBranch, worktreeStartPoint)
    if (useWorktree && !worktree) {
      setError('Worktree branch is required.')
      return
    }
    if (launch.launchMode === 'custom') {
      writeCustomLaunch({
        label: launch.launchLabel || 'custom',
        command: launch.launchCommand || '',
      })
    }
    onCreate(selectedDaemonId, workDir, tool, launch, worktree)
    onClose()
  }

  const title = connectedDaemons.length === 1 && selectedDaemon
    ? `New Session on ${selectedDaemon.name}`
    : 'New Session'

  return (
    <div className="dialog-overlay" onClick={onClose}>
      <div className="dialog" onClick={e => e.stopPropagation()}>
        <h3>{title}</h3>
        <form onSubmit={handleSubmit}>
          {connectedDaemons.length > 1 && (
            <label>
              Agent host
              <select
                value={selectedDaemonId}
                onChange={e => {
                  const nextDaemonId = e.target.value
                  const nextDaemon = connectedDaemons.find(daemon => daemon.id === nextDaemonId) || null
                  setDaemonId(nextDaemonId)
                  setWorkDir(getRecentWorkDirs(nextDaemon)[0] || '~')
                  setError(null)
                }}
              >
                {connectedDaemons.map(daemon => (
                  <option key={daemon.id} value={daemon.id}>
                    {daemon.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label>
            Tool
            <select
              value={tool}
              onChange={e => {
                const nextTool = e.target.value
                setTool(nextTool)
                if (!worktreeBranchTouched) {
                  setWorktreeBranch(defaultWorktreeBranch(nextTool))
                }
              }}
            >
              <option value="codex">Codex CLI</option>
              <option value="claude">Claude Code</option>
              <option value="bash">Bash terminal</option>
            </select>
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={useWorktree}
              onChange={e => {
                setUseWorktree(e.target.checked)
                setError(null)
              }}
            />
            Create worktree
          </label>
          {useWorktree && (
            <>
              <label>
                Branch
                <input
                  type="text"
                  value={worktreeBranch}
                  onChange={e => {
                    setWorktreeBranch(e.target.value)
                    setWorktreeBranchTouched(true)
                    setError(null)
                  }}
                  placeholder="agent/codex-20260507-120000"
                  required
                />
              </label>
              <label>
                Base ref
                <input
                  type="text"
                  value={worktreeStartPoint}
                  onChange={e => {
                    setWorktreeStartPoint(e.target.value)
                    setError(null)
                  }}
                  placeholder="HEAD"
                />
              </label>
            </>
          )}
          <label>
            Launch
            <select
              value={launchMode}
              onChange={e => {
                setLaunchMode(e.target.value as LaunchMode)
                setError(null)
              }}
            >
              <option value="local">Local</option>
              <option value="custom">Custom</option>
            </select>
          </label>
          {launchMode === 'custom' && (
            <>
              <label>
                Label
                <input
                  type="text"
                  value={launchLabel}
                  onChange={e => setLaunchLabel(e.target.value)}
                  placeholder="custom"
                />
              </label>
              <label>
                Command template
                <textarea
                  value={launchCommand}
                  onChange={e => {
                    setLaunchCommand(e.target.value)
                    setError(null)
                  }}
                  placeholder="srun --pty --chdir {workDir} --gres=gpu:1 {command}"
                  rows={3}
                  required
                />
              </label>
            </>
          )}
          <label>
            {useWorktree ? 'Source directory' : 'Working directory'}
            {recentWorkDirs.length > 0 && (
              <div className="recent-dir-list" aria-label="Recent directories">
                {recentWorkDirs.map(dir => (
                  <div
                    className={`recent-dir-row ${dir === workDir ? 'selected' : ''}`}
                    key={dir}
                  >
                    <button
                      type="button"
                      className="recent-dir-main"
                      onClick={() => {
                        setWorkDir(dir)
                      }}
                    >
                      <span className="recent-dir-name">{projectNameFromPath(dir)}</span>
                      <span className="recent-dir-path">{dir}</span>
                    </button>
                    {selectedDaemon && (
                      <button
                        type="button"
                        className="recent-dir-remove"
                        aria-label={`Remove ${dir} from recent directories`}
                        title="Remove"
                        onClick={() => onRemoveRecentWorkDir(selectedDaemon, dir)}
                      >
                        x
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
            <input
              type="text"
              value={workDir}
              onChange={e => {
                setWorkDir(e.target.value)
              }}
              placeholder="/path/to/project"
              required
            />
          </label>
          {error && <div className="dialog-error">{error}</div>}
          <div className="dialog-actions">
            <button type="button" onClick={onClose}>Cancel</button>
            <button type="submit" disabled={!selectedDaemon}>Create</button>
          </div>
        </form>
      </div>
    </div>
  )
}

function launchOptions(
  launchMode: LaunchMode,
  launchLabel: string,
  launchCommand: string,
): LaunchOptions {
  if (launchMode !== 'custom') {
    return { launchMode: 'local' }
  }
  return {
    launchMode: 'custom',
    launchLabel: launchLabel.trim() || 'custom',
    launchCommand: launchCommand.trim(),
  }
}

function worktreeOptions(
  enabled: boolean,
  sourceDir: string,
  branch: string,
  startPoint: string,
): WorktreeOptions | undefined {
  if (!enabled) return undefined
  const trimmedBranch = branch.trim()
  if (!trimmedBranch) return undefined
  const trimmedStartPoint = startPoint.trim()
  return {
    enabled: true,
    sourceDir,
    branch: trimmedBranch,
    startPoint: trimmedStartPoint || undefined,
  }
}

function defaultWorktreeBranch(tool: string): string {
  const now = new Date()
  const stamp = [
    now.getFullYear(),
    pad2(now.getMonth() + 1),
    pad2(now.getDate()),
  ].join('') + '-' + [
    pad2(now.getHours()),
    pad2(now.getMinutes()),
    pad2(now.getSeconds()),
  ].join('')
  return `agent/${tool}-${stamp}`
}

function pad2(value: number): string {
  return String(value).padStart(2, '0')
}

function readCustomLaunch(): { label: string; command: string } {
  try {
    const raw = window.localStorage.getItem(CUSTOM_LAUNCH_STORAGE_KEY)
    if (!raw) return { label: 'custom', command: '' }
    const parsed = JSON.parse(raw) as { label?: unknown; command?: unknown }
    return {
      label: typeof parsed.label === 'string' && parsed.label.trim() ? parsed.label : 'custom',
      command: typeof parsed.command === 'string' ? parsed.command : '',
    }
  } catch {
    return { label: 'custom', command: '' }
  }
}

function writeCustomLaunch(launch: { label: string; command: string }) {
  window.localStorage.setItem(CUSTOM_LAUNCH_STORAGE_KEY, JSON.stringify(launch))
}

function projectNameFromPath(path: string): string {
  const trimmed = path.trim()
  const cleaned = trimmed.replace(/[\\/]+$/, '')
  if (!cleaned || cleaned === '~') return 'Home'
  const parts = cleaned.split(/[\\/]+/)
  return parts[parts.length - 1] || cleaned
}
