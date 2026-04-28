import { useState } from 'react'
import { Daemon } from '../hooks/useSwitch'

interface Props {
  daemon: Daemon
  onClose: () => void
  onCreate: (
    daemonId: string,
    workDir: string,
    opts?: { tool?: string; model?: string; permissionMode?: string; initialPrompt?: string },
  ) => void
}

export function NewSessionDialog({ daemon, onClose, onCreate }: Props) {
  const [tool, setTool] = useState('claude')
  const [workDir, setWorkDir] = useState('~')
  const [model, setModel] = useState('')
  const [permissionMode, setPermissionMode] = useState('')
  const [initialPrompt, setInitialPrompt] = useState('')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    onCreate(daemon.id, workDir, {
      tool,
      model: model || undefined,
      permissionMode: permissionMode || undefined,
      initialPrompt: initialPrompt || undefined,
    })
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
            <input
              type="text"
              value={workDir}
              onChange={e => setWorkDir(e.target.value)}
              placeholder="/path/to/project"
              required
            />
          </label>
          {tool === 'codex' && (
            <label>
              Initial prompt {tool === 'codex' ? '(required for Codex)' : ''}
              <textarea
                value={initialPrompt}
                onChange={e => setInitialPrompt(e.target.value)}
                placeholder="e.g. fix the bug in main.py"
                rows={3}
                required={tool === 'codex'}
              />
            </label>
          )}
          <label>
            Model (optional)
            <input
              type="text"
              value={model}
              onChange={e => setModel(e.target.value)}
              placeholder={tool === 'claude' ? 'e.g. sonnet, opus' : 'e.g. o3, o4-mini'}
            />
          </label>
          <label>
            Permission mode (optional)
            <select value={permissionMode} onChange={e => setPermissionMode(e.target.value)}>
              <option value="">Default</option>
              {tool === 'claude' ? (
                <>
                  <option value="auto">Auto</option>
                  <option value="acceptEdits">Accept edits</option>
                  <option value="bypassPermissions">Bypass permissions</option>
                </>
              ) : (
                <>
                  <option value="auto">Full auto (auto-approve)</option>
                  <option value="acceptEdits">On request</option>
                </>
              )}
            </select>
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
