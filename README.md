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

# Or start the hub with a local daemon for development/single-machine use
switch hub --local-daemon

# Start a daemon (on each machine)
switch daemon --hub http://<hub-host>:9341

# Open http://localhost:9341
```

## CLI Reference

```
switch hub     [-p PORT] [--host HOST] [--local-daemon] [-v]  Start the hub + web UI
switch daemon  [-p PORT] [--hub URL] [-n NAME] [-v]           Start a daemon
switch update                                                 Update to the latest version
```

## Development

```bash
git clone git@github.com:edbeeching/switch.git
cd switch
uv tool install --force --editable .
```

This links the `switch` command to your local checkout — Python changes take effect immediately. To rebuild the web UI after frontend changes:

```bash
cd switch/web && npm install && npm run build
cp -r dist/* ../hub/static/
```

### Worktrees

Keep local worktrees inside the repo under `.worktrees/` so sandboxed coding agents can read and write them without needing permissions for sibling directories:

```bash
mkdir -p .worktrees
git worktree add .worktrees/<name> -b <branch> origin/main
```

The `.worktrees/` directory is ignored by Git. Avoid placing worktrees next to the repo, such as `../switch-main`, because those paths may sit outside an agent's writable workspace root.

## Supported Tools

| Tool | Status | Notes |
|------|--------|-------|
| Claude Code | Supported | Full bidirectional streaming via stream-json |
| Codex CLI | Supported | Fire-and-forget exec with resume for follow-ups |
