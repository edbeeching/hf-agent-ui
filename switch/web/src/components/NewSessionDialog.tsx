import { useState } from 'react'
import type { Daemon, LaunchMode, LaunchOptions } from '../hooks/useSwitch'

const CUSTOM_LAUNCH_STORAGE_KEY = 'switch.customLaunch'

interface Props {
  daemon: Daemon
  recentWorkDirs: string[]
  onClose: () => void
  onCreate: (
    daemonId: string,
    workDir: string,
    tool: string,
    launch: LaunchOptions,
  ) => void
}

export function NewSessionDialog({ daemon, recentWorkDirs, onClose, onCreate }: Props) {
  const storedCustomLaunch = readCustomLaunch()
  const [tool, setTool] = useState('claude')
  const [workDir, setWorkDir] = useState(recentWorkDirs[0] || '~')
  const [launchMode, setLaunchMode] = useState<LaunchMode>('local')
  const [launchLabel, setLaunchLabel] = useState(storedCustomLaunch.label)
  const [launchCommand, setLaunchCommand] = useState(storedCustomLaunch.command)
  const [error, setError] = useState<string | null>(null)

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const launch = launchOptions(launchMode, launchLabel, launchCommand)
    if (launch.launchMode === 'custom' && !launch.launchCommand?.includes('{command}')) {
      setError('Custom launch command must include {command}.')
      return
    }
    if (launch.launchMode === 'custom') {
      writeCustomLaunch({
        label: launch.launchLabel || 'custom',
        command: launch.launchCommand || '',
      })
    }
    onCreate(daemon.id, workDir, tool, launch)
    onClose()
  }

  return (
    <div className="dialog-overlay" onClick={onClose}>
      <div className="dialog" onClick={e => e.stopPropagation()}>
        <h3>New Session on {daemon.name}</h3>
        <form onSubmit={handleSubmit}>
          <label>
            Tool
            <select value={tool} onChange={e => setTool(e.target.value)}>
              <option value="claude">Claude Code</option>
              <option value="codex">Codex CLI</option>
            </select>
          </label>
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
            Working directory
            {recentWorkDirs.length > 0 && (
              <select
                className="recent-dir-select"
                value={recentWorkDirs.includes(workDir) ? workDir : ''}
                onChange={e => setWorkDir(e.target.value || workDir)}
              >
                <option value="">Recent directories</option>
                {recentWorkDirs.map(dir => (
                  <option key={dir} value={dir}>{dir}</option>
                ))}
              </select>
            )}
            <input
              type="text"
              value={workDir}
              onChange={e => setWorkDir(e.target.value)}
              placeholder="/path/to/project"
              required
            />
          </label>
          {error && <div className="dialog-error">{error}</div>}
          <div className="dialog-actions">
            <button type="button" onClick={onClose}>Cancel</button>
            <button type="submit">Create</button>
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
