---
title: agentic-ui
sdk: docker
app_port: 7860
---

# agentic-ui

Web-based mission control for AI coding sessions. Manage Claude Code and Codex CLI sessions across multiple local, remote, and container agent hosts from a single browser tab.

## Architecture

```
Browser <--WS--> Hub (FastAPI) <--WS--> Agent host (Python) <--stdio--> Claude / Codex CLI
```

- **Hub** — central server, agent host registry, WebSocket relay, serves the web UI
- **Agent host** — runs on each local, remote, or container machine, wraps AI CLI tools, and connects outbound to the hub

## Install

```bash
uv -vv tool install --force --reinstall git+ssh://git@github.com/edbeeching/agentic-ui.git
```

To update:

```bash
switch update
```

## Quick Start

```bash
# Start the hub (serves the web UI on :9341)
switch hub

# Or start the hub with a local agent host for development/single-machine use
switch hub --local-agent-host

# Start an agent host (on each machine)
switch host --hub http://<hub-host>:9341

# Open http://localhost:9341
```

## Hugging Face Space

agentic-ui can run as a private Docker Space. Configure the Space with:

```yaml
sdk: docker
app_port: 7860
```

Set a Space secret:

```bash
SWITCH_DAEMON_TOKEN=<shared-secret>
```

For private/internal Spaces, optionally expose the agent host token in the web UI copy command:

```bash
SWITCH_EXPOSE_DAEMON_TOKEN=1
```

Then install and start agent hosts on remote machines:

```bash
uv -vv tool install --force --reinstall git+ssh://git@github.com/edbeeching/agentic-ui.git
SWITCH_DAEMON_TOKEN=<shared-secret> switch host --hub https://<space-subdomain>.hf.space
```

For private Spaces, also provide a Hugging Face access token via env:

```bash
export HF_TOKEN=<hf-token>
export SWITCH_DAEMON_TOKEN=<shared-secret>
switch host --hub https://<space-subdomain>.hf.space
```

### Space Deploys

The GitHub workflow `Deploy HF Space` uploads `main` to the private Space after CI passes. Configure a GitHub Actions repository secret with write access to the Space:

```bash
HF_TOKEN=<hf-write-token>
```

## CLI Reference

```
switch hub   [-p PORT] [--host HOST] [--local-agent-host] [-v]  Start the hub + web UI
switch host  [--hub URL] [--token TOKEN] [--hf-token TOKEN] [-n NAME] [-v]  Start an agent host
switch daemon                                                        Backward-compatible alias for switch host
switch update                                                        Update to the latest version
```

## Development

```bash
git clone git@github.com:edbeeching/agentic-ui.git
cd agentic-ui
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

The `.worktrees/` directory is ignored by Git. Avoid placing worktrees next to the repo, such as `../agentic-ui-main`, because those paths may sit outside an agent's writable workspace root.

## Supported Tools

| Tool | Status | Notes |
|------|--------|-------|
| Claude Code | Supported | Full bidirectional streaming via stream-json |
| Codex CLI | Supported | Fire-and-forget exec with resume for follow-ups |
