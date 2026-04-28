import { useEffect, useRef } from 'react'
import type { SessionMessage } from '../hooks/useSwitch'

interface Props {
  messages: SessionMessage[]
  sessionId: string
}

export function SessionView({ messages, sessionId }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  if (!sessionId) {
    return (
      <div className="session-view-empty">
        Select a session or create a new one
      </div>
    )
  }

  return (
    <div className="session-view" ref={scrollRef}>
      {messages.map(msg => (
        <MessageBlock key={msg.id} message={msg} />
      ))}
    </div>
  )
}

function MessageBlock({ message }: { message: SessionMessage }) {
  if (message.type === 'stderr') {
    return (
      <div className="msg msg-stderr">
        <pre>{message.text}</pre>
      </div>
    )
  }

  if (message.type === 'exit') {
    return (
      <div className="msg msg-exit">
        Session exited with code {message.code}
      </div>
    )
  }

  if (message.type === 'message' && message.data) {
    return <StreamEventBlock data={message.data} />
  }

  return null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isTextPart(value: unknown): value is { type: 'text'; text: string } {
  return isRecord(value) && value.type === 'text' && typeof value.text === 'string'
}

function StreamEventBlock({ data }: { data: unknown }) {
  if (!isRecord(data)) {
    return <div className="msg msg-raw"><pre>{String(data)}</pre></div>
  }

  // === Shared types ===
  if (data.type === 'raw') {
    return <div className="msg msg-raw"><pre>{String(data.text || '')}</pre></div>
  }

  // System/info messages (both tools)
  if (data.type === 'system') {
    if (data.subtype === 'init') {
      return (
        <div className="msg msg-system">
          Session initialized — model: {String(data.model || 'unknown')}
        </div>
      )
    }
    if (typeof data.text === 'string') {
      return <div className="msg msg-system">{data.text}</div>
    }
    return null
  }

  // === Claude Code events ===

  if (data.type === 'result') {
    return (
      <div className="msg msg-result">
        <div className="msg-label">Result</div>
        <pre>{JSON.stringify(data, null, 2)}</pre>
      </div>
    )
  }

  if (data.type === 'content_block_delta' && isRecord(data.delta) && typeof data.delta.text === 'string') {
    return <span className="msg-text-delta">{data.delta.text}</span>
  }

  if (data.type === 'assistant') {
    const content = isRecord(data.message) ? data.message.content : undefined
    if (Array.isArray(content)) {
      return (
        <div className="msg msg-assistant">
          {content.map((block, i: number) => {
            if (!isRecord(block)) {
              return <pre key={i}>{JSON.stringify(block, null, 2)}</pre>
            }
            if (block.type === 'text') {
              return <pre key={i} className="msg-text">{String(block.text || '')}</pre>
            }
            if (block.type === 'tool_use') {
              return (
                <div key={i} className="msg-tool-use">
                  <div className="msg-label">Tool: {String(block.name || 'unknown')}</div>
                  <pre>{JSON.stringify(block.input, null, 2)}</pre>
                </div>
              )
            }
            return <pre key={i}>{JSON.stringify(block, null, 2)}</pre>
          })}
        </div>
      )
    }
  }

  // Claude wraps events as { type: "stream_event", event: { ... } } — unwrap and render the inner event
  if (data.type === 'stream_event' && data.event) {
    return <StreamEventBlock data={data.event} />
  }

  // === Codex CLI events ===

  if (data.type === 'thread.started') {
    return (
      <div className="msg msg-system">
        Codex session started (id: {String(data.session_id || 'unknown')})
      </div>
    )
  }

  if (data.type === 'turn.started') {
    return null // Noisy, skip
  }

  if (data.type === 'turn.completed') {
    return (
      <div className="msg msg-system">
        Turn completed
      </div>
    )
  }

  if (data.type === 'turn.failed') {
    return (
      <div className="msg msg-stderr">
        <pre>Turn failed: {typeof data.error === 'string' ? data.error : JSON.stringify(data)}</pre>
      </div>
    )
  }

  // Codex item events (text output, file changes, etc.)
  if (typeof data.type === 'string' && data.type.startsWith('item.')) {
    const item = isRecord(data.item) ? data.item : data
    // Text output
    if (item.type === 'message' && item.content) {
      const textParts = Array.isArray(item.content)
        ? item.content.filter(isTextPart).map(c => c.text)
        : [String(item.content)]
      return (
        <div className="msg msg-assistant">
          {textParts.map((text: string, i: number) => (
            <pre key={i} className="msg-text">{text}</pre>
          ))}
        </div>
      )
    }
    // Tool use / function call
    if (item.type === 'function_call' || item.type === 'tool_use') {
      const functionInfo = isRecord(item.function) ? item.function : undefined
      return (
        <div className="msg-tool-use">
          <div className="msg-label">Tool: {String(item.name || functionInfo?.name || 'unknown')}</div>
          <pre>{JSON.stringify(item.arguments || item.input || functionInfo?.arguments, null, 2)}</pre>
        </div>
      )
    }
    // Tool result
    if (item.type === 'function_call_output') {
      return (
        <div className="msg msg-result">
          <div className="msg-label">Tool Output</div>
          <pre>{typeof item.output === 'string' ? item.output : JSON.stringify(item.output, null, 2)}</pre>
        </div>
      )
    }
  }

  if (data.type === 'error') {
    return (
      <div className="msg msg-stderr">
        <pre>{typeof data.message === 'string' ? data.message : JSON.stringify(data)}</pre>
      </div>
    )
  }

  // Fallback
  return (
    <div className="msg msg-unknown">
      <pre>{JSON.stringify(data, null, 2)}</pre>
    </div>
  )
}
