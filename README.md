# Switch

Web-based mission control for AI coding sessions. Manage Claude Code and Codex CLI sessions across multiple remote machines from a single browser tab.

## Architecture

```
Browser <--WS--> Hub (FastAPI) <--WS--> Daemon (Python) <--stdio--> Claude / Codex CLI
```

- **Daemon** — runs on each remote machine, wraps AI CLI tools, exposes WebSocket API
- **Hub** — central server, daemon registry, WebSocket relay, serves the web UI
- **Web** — React dashboard with real-time session streaming

## Quick Start

```bash
# Install
uv sync

# Terminal 1 — start the hub
uv run switch hub

# Terminal 2 — start a daemon
uv run switch daemon

# Terminal 3 — start the web UI
uv run switch web
# Open http://localhost:5173
```

For remote machines, point the daemon at your hub:

```bash
uv run switch daemon --hub http://<hub-host>:9341 --name my-server
```

## CLI Reference

```
switch hub     [-p PORT] [--host HOST] [-v]     Start the hub (default :9341)
switch daemon  [-p PORT] [--hub URL] [-n NAME] [-v]  Start a daemon (default :9340)
switch web     [-p PORT]                        Start the web UI (default :5173)
```

## Supported Tools

| Tool | Status | Notes |
|------|--------|-------|
| Claude Code | Supported | Full bidirectional streaming via stream-json |
| Codex CLI | Supported | Fire-and-forget exec with resume for follow-ups |
