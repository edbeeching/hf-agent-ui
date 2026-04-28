# Switch

Web-based mission control for AI coding sessions. Manage Claude Code and Codex CLI sessions across multiple remote machines from a single browser tab.

## Architecture

```
Browser <--WS--> Hub (FastAPI) <--WS--> Daemon (Python) <--stdio--> Claude / Codex CLI
```

- **Hub** — central server, daemon registry, WebSocket relay, serves the web UI
- **Daemon** — runs on each remote machine, wraps AI CLI tools, exposes WebSocket API

## Install

```bash
uv tool install git+ssh://git@github.com/edbeeching/switch.git
```

To update:

```bash
switch update
```

## Quick Start

```bash
# Start the hub (serves the web UI on :9341)
switch hub

# Start a daemon (on each machine)
switch daemon --hub http://<hub-host>:9341

# Open http://localhost:9341
```

## CLI Reference

```
switch hub     [-p PORT] [--host HOST] [-v]          Start the hub + web UI (default :9341)
switch daemon  [-p PORT] [--hub URL] [-n NAME] [-v]  Start a daemon (default :9340)
switch update                                        Update to the latest version
```

## Supported Tools

| Tool | Status | Notes |
|------|--------|-------|
| Claude Code | Supported | Full bidirectional streaming via stream-json |
| Codex CLI | Supported | Fire-and-forget exec with resume for follow-ups |
