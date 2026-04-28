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

### 1. Start the hub

```bash
cd hub
uv sync
uv run switch-hub
# or: uv run switch-hub --port 9341 --verbose
```

### 2. Start a daemon (on each machine)

```bash
cd daemon
uv sync
uv run switch-daemon --hub http://<hub-host>:9341
# or: uv run switch-daemon --port 9340 --name my-server --verbose
```

### 3. Open the web UI

```bash
cd web
npm install
npm run dev
# Open http://localhost:5173
```

## CLI Reference

### switch-hub

```
usage: switch-hub [-h] [-p PORT] [--host HOST] [-v]

options:
  -p, --port PORT    HTTP/WebSocket port (default: 9341)
  --host HOST        Bind address (default: 0.0.0.0)
  -v, --verbose      Debug logging
```

### switch-daemon

```
usage: switch-daemon [-h] [-p PORT] [--hub HUB] [-n NAME] [-v]

options:
  -p, --port PORT    WebSocket port (default: 9340)
  --hub HUB          Hub URL (default: http://localhost:9341)
  -n, --name NAME    Display name (default: daemon-<port>)
  -v, --verbose      Debug logging
```

## Supported Tools

| Tool | Status | Notes |
|------|--------|-------|
| Claude Code | Supported | Full bidirectional streaming via stream-json |
| Codex CLI | Supported | Fire-and-forget exec with resume for follow-ups |
