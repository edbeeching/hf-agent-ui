import { useState } from 'react'
import type { Daemon } from '../hooks/useSwitch'

interface Props {
  daemon: Daemon
  recentWorkDirs: string[]
  onClose: () => void
  onCreate: (
    daemonId: string,
    workDir: string,
    tool: string,
  ) => void
}

export function NewSessionDialog({ daemon, recentWorkDirs, onClose, onCreate }: Props) {
  const [tool, setTool] = useState('claude')
  const [workDir, setWorkDir] = useState(recentWorkDirs[0] || '~')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    onCreate(daemon.id, workDir, tool)
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
          <div className="dialog-actions">
            <button type="button" onClick={onClose}>Cancel</button>
            <button type="submit">Create</button>
          </div>
        </form>
      </div>
    </div>
  )
}
