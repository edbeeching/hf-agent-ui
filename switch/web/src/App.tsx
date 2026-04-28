import { useState } from 'react'
import { useSwitch } from './hooks/useSwitch'
import { DaemonList } from './components/DaemonList'
import { TerminalView } from './components/TerminalView'
import { NewSessionDialog } from './components/NewSessionDialog'
import './App.css'

function App() {
  const sw = useSwitch()
  const [selected, setSelected] = useState<{ daemonId: string; sessionId: string } | null>(null)
  const [newSessionDaemonId, setNewSessionDaemonId] = useState<string | null>(null)

  const selectedPtyOutput = selected ? sw.ptyOutput.get(selected.sessionId) || [] : []
  const newSessionDaemon = newSessionDaemonId
    ? sw.daemons.find(d => d.id === newSessionDaemonId)
    : null

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="sidebar-title">
          <h1>Switch</h1>
          <span className={`connection-badge ${sw.connected ? 'connected' : ''}`}>
            {sw.connected ? 'Connected' : 'Disconnected'}
          </span>
        </div>
        <DaemonList
          daemons={sw.daemons}
          sessions={sw.sessions}
          selectedSession={selected}
          onSelectSession={(daemonId, sessionId) => setSelected({ daemonId, sessionId })}
          onNewSession={daemonId => setNewSessionDaemonId(daemonId)}
        />
      </aside>

      <main className="main-panel">
        <TerminalView
          sessionId={selected?.sessionId || ''}
          output={selectedPtyOutput}
          onInput={data => {
            if (selected) sw.sendPtyInput(selected.daemonId, selected.sessionId, data)
          }}
          onResize={(cols, rows) => {
            if (selected) sw.resizePty(selected.daemonId, selected.sessionId, cols, rows)
          }}
        />
      </main>

      {newSessionDaemon && (
        <NewSessionDialog
          daemon={newSessionDaemon}
          onClose={() => setNewSessionDaemonId(null)}
          onCreate={(daemonId, workDir, tool) => {
            sw.createPtySession(daemonId, workDir, tool)
          }}
        />
      )}
    </div>
  )
}

export default App
