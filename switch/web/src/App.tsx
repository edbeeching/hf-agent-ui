import { useEffect, useState } from 'react'
import { useSwitch } from './hooks/useSwitch'
import { DaemonList } from './components/DaemonList'
import { TerminalView } from './components/TerminalView'
import { NewSessionDialog } from './components/NewSessionDialog'
import './App.css'

const SELECTED_SESSION_STORAGE_KEY = 'switch.selectedSession'

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
    listSessions,
    subscribeSession,
  } = sw
  const [selected, setSelected] = useState<{ daemonId: string; sessionId: string } | null>(() => readStoredSelection())
  const [newSessionDaemonId, setNewSessionDaemonId] = useState<string | null>(null)

  const selectedPtyOutput = selected ? ptyOutput.get(selected.sessionId) || [] : []
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
    if (selected) {
      window.localStorage.setItem(SELECTED_SESSION_STORAGE_KEY, JSON.stringify(selected))
      if (connected) {
        subscribeSession(selected.daemonId, selected.sessionId)
      }
    } else {
      window.localStorage.removeItem(SELECTED_SESSION_STORAGE_KEY)
    }
  }, [connected, selected, subscribeSession])

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
            if (selected) sendPtyInput(selected.daemonId, selected.sessionId, data)
          }}
          onResize={(cols, rows) => {
            if (selected) resizePty(selected.daemonId, selected.sessionId, cols, rows)
          }}
        />
      </main>

      {newSessionDaemon && (
        <NewSessionDialog
          daemon={newSessionDaemon}
          onClose={() => setNewSessionDaemonId(null)}
          onCreate={(daemonId, workDir, tool) => {
            createPtySession(daemonId, workDir, tool)
          }}
        />
      )}
    </div>
  )
}

export default App

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
