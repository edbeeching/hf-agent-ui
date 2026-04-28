import { useState } from 'react'
import { useSwitch } from './hooks/useSwitch'
import { DaemonList } from './components/DaemonList'
import { SessionView } from './components/SessionView'
import { MessageInput } from './components/MessageInput'
import { NewSessionDialog } from './components/NewSessionDialog'
import './App.css'

function App() {
  const sw = useSwitch()
  const [selected, setSelected] = useState<{ daemonId: string; sessionId: string } | null>(null)
  const [newSessionDaemonId, setNewSessionDaemonId] = useState<string | null>(null)

  const selectedMessages = selected ? sw.messages.get(selected.sessionId) || [] : []
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
        <SessionView
          messages={selectedMessages}
          sessionId={selected?.sessionId || ''}
        />
        <MessageInput
          disabled={!selected}
          onSend={msg => {
            if (selected) {
              sw.sendMessage(selected.daemonId, selected.sessionId, msg)
            }
          }}
        />
      </main>

      {newSessionDaemon && (
        <NewSessionDialog
          daemon={newSessionDaemon}
          onClose={() => setNewSessionDaemonId(null)}
          onCreate={(daemonId, workDir, opts) => {
            sw.createSession(daemonId, workDir, opts)
          }}
        />
      )}
    </div>
  )
}

export default App
