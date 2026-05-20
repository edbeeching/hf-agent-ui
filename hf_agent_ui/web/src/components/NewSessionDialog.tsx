import { useEffect, useState } from 'react'
import type { Daemon, LaunchMode, LaunchOptions, WorktreeListResult, WorktreeOptions } from '../hooks/useAgentUi'

const CUSTOM_LAUNCH_STORAGE_KEY = 'hf-agent-ui.customLaunch'
type WorktreeMode = 'none' | 'create' | 'existing'

interface Props {
  daemons: Daemon[]
  getRecentWorkDirs: (daemon: Daemon | null) => string[]
  getWorktreeList: (daemonId: string, sourceDir: string) => WorktreeListResult | null
  onListWorktrees: (daemonId: string, sourceDir: string) => void
  onRemoveRecentWorkDir: (daemon: Daemon, workDir: string) => void
  onClose: () => void
  onCreate: (
    daemonId: string,
    workDir: string,
    tool: string,
    launch: LaunchOptions,
    worktree?: WorktreeOptions,
    label?: string | null,
  ) => void
}

export function NewSessionDialog({
  daemons,
  getRecentWorkDirs,
  getWorktreeList,
  onListWorktrees,
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
  const [sessionLabel, setSessionLabel] = useState('')
  const [workDir, setWorkDir] = useState(getRecentWorkDirs(defaultDaemon)[0] || '~')
  const [launchMode, setLaunchMode] = useState<LaunchMode>('local')
  const [launchLabel, setLaunchLabel] = useState(storedCustomLaunch.label)
  const [launchCommand, setLaunchCommand] = useState(storedCustomLaunch.command)
  const [worktreeMode, setWorktreeMode] = useState<WorktreeMode>('none')
  const [worktreeBranch, setWorktreeBranch] = useState(() => defaultWorktreeBranch('codex'))
  const [worktreeBranchTouched, setWorktreeBranchTouched] = useState(false)
  const [worktreeStartPoint, setWorktreeStartPoint] = useState('HEAD')
  const [selectedWorktree, setSelectedWorktree] = useState<{
    daemonId: string
    sourceDir: string
    root: string
  } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const selectedDaemonId = connectedDaemons.some(daemon => daemon.id === daemonId)
    ? daemonId
    : defaultDaemonId
  const selectedDaemon = connectedDaemons.find(daemon => daemon.id === selectedDaemonId) || null
  const recentWorkDirs = getRecentWorkDirs(selectedDaemon)
  const sourceDir = workDir.trim() || '.'
  const worktreeList = worktreeMode === 'existing' && selectedDaemonId
    ? getWorktreeList(selectedDaemonId, sourceDir)
    : null
  const selectedWorktreeRoot = selectedWorktree?.daemonId === selectedDaemonId
    && selectedWorktree.sourceDir === sourceDir
    ? selectedWorktree.root
    : ''

  useEffect(() => {
    if (worktreeMode !== 'existing' || !selectedDaemonId || !sourceDir) return
    const timeout = window.setTimeout(() => {
      onListWorktrees(selectedDaemonId, sourceDir)
    }, 250)
    return () => window.clearTimeout(timeout)
  }, [worktreeMode, selectedDaemonId, sourceDir, onListWorktrees])

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
    const worktree = worktreeOptions(worktreeMode, workDir, worktreeBranch, worktreeStartPoint, selectedWorktreeRoot)
    if (worktreeMode === 'create' && !worktree) {
      setError('Worktree branch is required.')
      return
    }
    if (worktreeMode === 'existing' && !worktree) {
      setError('Select an existing worktree.')
      return
    }
    if (launch.launchMode === 'custom') {
      writeCustomLaunch({
        label: launch.launchLabel || 'custom',
        command: launch.launchCommand || '',
      })
    }
    onCreate(selectedDaemonId, workDir, tool, launch, worktree, normalizeSessionLabel(sessionLabel))
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
          <label>
            Session label
            <input
              type="text"
              value={sessionLabel}
              onChange={e => setSessionLabel(e.target.value)}
              placeholder="auth fix, tests, review"
              maxLength={120}
            />
          </label>
          <label>
            Worktree
            <select
              value={worktreeMode}
              onChange={e => {
                setWorktreeMode(e.target.value as WorktreeMode)
                setSelectedWorktree(null)
                setError(null)
              }}
            >
              <option value="none">None</option>
              <option value="create">Create new</option>
              <option value="existing">Use existing</option>
            </select>
          </label>
          {worktreeMode === 'create' && (
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
            {worktreeMode === 'none' ? 'Working directory' : 'Source directory'}
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
                setError(null)
              }}
              placeholder="/path/to/project"
              required
            />
          </label>
          {worktreeMode === 'existing' && (
            <WorktreePicker
              result={worktreeList}
              selectedRoot={selectedWorktreeRoot}
              onSelect={root => {
                setSelectedWorktree({ daemonId: selectedDaemonId, sourceDir, root })
                setError(null)
              }}
            />
          )}
          {error && <div className="dialog-error">{error}</div>}
          <div className="dialog-actions">
            <button type="button" onClick={onClose}>Cancel</button>
            <button
              type="submit"
              disabled={!selectedDaemon || (worktreeMode === 'existing' && !selectedWorktreeRoot)}
            >
              Create
            </button>
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
  mode: WorktreeMode,
  sourceDir: string,
  branch: string,
  startPoint: string,
  worktreeRoot: string,
): WorktreeOptions | undefined {
  if (mode === 'none') return undefined
  if (mode === 'existing') {
    const trimmedRoot = worktreeRoot.trim()
    if (!trimmedRoot) return undefined
    return {
      enabled: true,
      mode: 'existing',
      sourceDir,
      worktreeRoot: trimmedRoot,
    }
  }
  const trimmedBranch = branch.trim()
  if (!trimmedBranch) return undefined
  const trimmedStartPoint = startPoint.trim()
  return {
    enabled: true,
    mode: 'create',
    sourceDir,
    branch: trimmedBranch,
    startPoint: trimmedStartPoint || undefined,
  }
}

function WorktreePicker({
  result,
  selectedRoot,
  onSelect,
}: {
  result: WorktreeListResult | null
  selectedRoot: string
  onSelect: (root: string) => void
}) {
  const worktrees = result?.worktrees || []
  return (
    <div className="worktree-picker" aria-label="Existing worktrees">
      {result?.loading && worktrees.length === 0 && (
        <div className="worktree-picker-status">Loading worktrees...</div>
      )}
      {result?.error && (
        <div className="worktree-picker-status error">{result.error}</div>
      )}
      {!result?.loading && !result?.error && worktrees.length === 0 && (
        <div className="worktree-picker-status">No linked worktrees found.</div>
      )}
      {worktrees.map(worktree => (
        <button
          type="button"
          key={worktree.worktree_root}
          className={`worktree-row ${selectedRoot === worktree.worktree_root ? 'selected' : ''}`}
          disabled={!worktree.available}
          title={worktree.available ? worktree.work_dir : worktree.unavailable_reason || worktree.work_dir}
          onClick={() => onSelect(worktree.worktree_root)}
        >
          <span className="worktree-row-main">
            <span className="worktree-row-branch">{worktree.branch}</span>
            <span className="worktree-row-path">{compactPath(worktree.worktree_root)}</span>
          </span>
          <span className={`worktree-row-status ${worktree.available ? 'available' : 'unavailable'}`}>
            {worktree.available ? 'Ready' : 'Missing'}
          </span>
        </button>
      ))}
      {result?.loading && worktrees.length > 0 && (
        <div className="worktree-picker-status">Refreshing...</div>
      )}
    </div>
  )
}

function normalizeSessionLabel(label: string): string | null {
  const trimmed = label.trim()
  return trimmed || null
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

function compactPath(path: string): string {
  const trimmed = path.trim().replace(/[\\/]+$/, '')
  if (!trimmed || trimmed === '~') return 'Home'
  const parts = trimmed.split(/[\\/]+/).filter(Boolean)
  if (parts.length <= 2) return trimmed
  return `${parts[parts.length - 2]}/${parts[parts.length - 1]}`
}
