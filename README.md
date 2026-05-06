---
title: agentic-ui
sdk: docker
app_port: 7860
fullWidth: true
header: mini
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
# Start the hub on localhost (serves the web UI on :9341)
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

Set a Space variable so agentic-ui trusts Hugging Face's private Space access control for the browser UI:

```bash
SWITCH_TRUST_PROXY_AUTH=1
```

For private/internal single-user Spaces only, you can optionally expose the agent host token in the web UI copy command:

```bash
SWITCH_UNSAFE_EXPOSE_HOST_TOKEN=1
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

### Cloud Agent Hosts

The Space UI can launch an agent host as a Hugging Face Job. Configure Space secrets:

```bash
HF_TOKEN=<hf-token-with-job-read-write>
SWITCH_DAEMON_TOKEN=<shared-secret>
```

Optional Space variables:

```bash
SWITCH_HF_SPACE_REPO_ID=edbeeching/agentic-ui
SWITCH_HF_JOBS_NAMESPACE=edbeeching
SWITCH_HF_JOBS_DEFAULT_IMAGE=python:3.12
SWITCH_HF_JOBS_DEFAULT_FLAVOR=cpu-basic
SWITCH_HF_JOBS_DEFAULT_TIMEOUT=2h
```

The default image installs agentic-ui from the private Space repo and connects back to the hub. Images used for real sessions must also include the Claude or Codex CLI and any credentials those tools require.

### Space Deploys

The GitHub workflow `Deploy HF Space` uploads `main` to the private Space after CI passes. Configure a GitHub Actions repository secret with write access to the Space:

```bash
HF_TOKEN=<hf-write-token>
```

## CLI Reference

```
switch hub   [-p PORT] [--host HOST] [--local-agent-host] [--allow-insecure] [-v]  Start the hub + web UI
switch host  [--hub URL] [--token TOKEN] [--hf-token TOKEN] [-n NAME] [-v]  Start an agent host
switch daemon                                                        Backward-compatible alias for switch host
switch update                                                        Update to the latest version
```

By default `switch hub` binds to `127.0.0.1`. To expose the hub on a network interface, configure browser auth first:

```bash
export SWITCH_UI_TOKEN=<browser-token>
switch hub --host 0.0.0.0
```

Open the UI with the token once. The fragment is not sent to the server; the app stores an HttpOnly browser cookie for API and WebSocket auth.

```text
http://<hub-host>:9341/#uiToken=<browser-token>
```

`--allow-insecure` can be used for trusted local-network experiments, but it exposes browser control of connected agent hosts.

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
