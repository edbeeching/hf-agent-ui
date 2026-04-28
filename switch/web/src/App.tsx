import { useState } from 'react'
import { useSwitch } from './hooks/useSwitch'
import type { SessionInfo } from './hooks/useSwitch'
import { DaemonList } from './components/DaemonList'
import { SessionView } from './components/SessionView'
import { TerminalView } from './components/TerminalView'
import { MessageInput } from './components/MessageInput'
import { NewSessionDialog } from './components/NewSessionDialog'
import './App.css'

function App() {
  const sw = useSwitch()
  const [selected, setSelected] = useState<{ daemonId: string; sessionId: string } | null>(null)
  const [newSessionDaemonId, setNewSessionDaemonId] = useState<string | null>(null)

  const selectedMessages = selected ? sw.messages.get(selected.sessionId) || [] : []
  const selectedPtyOutput = selected ? sw.ptyOutput.get(selected.sessionId) || [] : []
  const newSessionDaemon = newSessionDaemonId
    ? sw.daemons.find(d => d.id === newSessionDaemonId)
    : null

  // Find selected session info to determine mode
  let selectedSession: SessionInfo | null = null
  if (selected) {
    for (const [, list] of sw.sessions) {
      const found = list.find(s => s.id === selected.sessionId)
      if (found) { selectedSession = found; break }
    }
  }
  const isPty = selectedSession?.mode === 'pty'

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
        {isPty && selected ? (
          <TerminalView
            sessionId={selected.sessionId}
            daemonId={selected.daemonId}
            output={selectedPtyOutput}
            onInput={data => sw.sendPtyInput(selected.daemonId, selected.sessionId, data)}
            onResize={(cols, rows) => sw.resizePty(selected.daemonId, selected.sessionId, cols, rows)}
          />
        ) : (
          <>
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
          </>
        )}
      </main>

      {newSessionDaemon && (
        <NewSessionDialog
          daemon={newSessionDaemon}
          onClose={() => setNewSessionDaemonId(null)}
          onCreateJson={(daemonId, workDir, opts) => {
            sw.createSession(daemonId, workDir, opts)
          }}
          onCreatePty={(daemonId, workDir, tool) => {
            sw.createPtySession(daemonId, workDir, tool)
          }}
        />
      )}
    </div>
  )
}

export default App
