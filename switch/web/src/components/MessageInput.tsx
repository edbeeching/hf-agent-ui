import { useState, type KeyboardEvent } from 'react'

interface Props {
  onSend: (message: string) => void
  disabled: boolean
}

export function MessageInput({ onSend, disabled }: Props) {
  const [value, setValue] = useState('')

  function handleSend() {
    const msg = value.trim()
    if (!msg) return
    onSend(msg)
    setValue('')
  }

  function handleKeyDown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="message-input">
      <textarea
        value={value}
        onChange={e => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={disabled ? 'Select a session first...' : 'Type a message... (Enter to send, Shift+Enter for newline)'}
        disabled={disabled}
        rows={3}
      />
      <button onClick={handleSend} disabled={disabled || !value.trim()}>
        Send
      </button>
    </div>
  )
}
