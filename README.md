---
title: agentic-ui
sdk: docker
app_port: 7860
fullWidth: true
header: mini
---

# agentic-ui

Browser control for AI coding sessions. agentic-ui manages Claude Code and Codex CLI sessions across local machines, remote servers, and cloud/container agent hosts from one web UI.

## Architecture

```text
Browser <--WS--> Hub (FastAPI) <--WS--> Agent host (Python) <--stdio--> Claude / Codex CLI
```

- **Hub**: central FastAPI server, browser UI, agent-host registry, and WebSocket relay.
- **Agent host**: process running on a local, remote, or container machine. It starts Claude/Codex sessions and connects outbound to the hub.

## Install

The project is currently private and not published as an official package:

```bash
uv -vv tool install --force --reinstall git+ssh://git@github.com/edbeeching/agentic-ui.git
```

Update an installed copy:

```bash
switch update
```

## Quick Start

Start the hub:

```bash
switch hub
```

Open `http://localhost:9341`.

For single-machine development or debugging, start the hub with a local agent host:

```bash
switch hub --local-agent-host
```

To connect another machine to a hub:

```bash
switch host --hub http://<hub-host>:9341
```

By default `switch hub` binds to `127.0.0.1`. To expose it on a network interface, configure browser auth first:

```bash
export SWITCH_UI_TOKEN=<browser-token>
switch hub --host 0.0.0.0
```

Open the UI once with:

```text
http://<hub-host>:9341/#uiToken=<browser-token>
```

`--allow-insecure` can be used for trusted local-network experiments, but it exposes browser control of connected agent hosts.

## Environments

| Environment | Branch | Space | URL | Deploy behavior |
|-------------|--------|-------|-----|-----------------|
| Development | `main` | `edbeeching/agentic-ui-dev` | `https://edbeeching-agentic-ui-dev.hf.space` | Auto-deploy after `main` CI passes |
| Production | `prod` | `edbeeching/agentic-ui` | `https://edbeeching-agentic-ui.hf.space` | Auto-deploy after `prod` CI passes |

Feature work should land through PRs into `main`. Production releases should be PRs from `main` into `prod` after the dev Space has been validated.

Branch protection is not currently enforceable for this private repository setup, so production gating is by PR convention plus CI until the repository is public or branch protection is available.

## Hugging Face Spaces

Both Spaces are private Docker Spaces using the front matter at the top of this README:

```yaml
sdk: docker
app_port: 7860
```

Each Space needs:

```bash
SWITCH_DAEMON_TOKEN=<environment-specific-shared-secret>
HF_TOKEN=<hf-token-with-space-and-jobs-access>
```

Each Space also needs:

```bash
SWITCH_TRUST_PROXY_AUTH=1
SWITCH_HF_SPACE_REPO_ID=<space-repo-id>
```

Use `SWITCH_HF_SPACE_REPO_ID=edbeeching/agentic-ui-dev` for dev and `SWITCH_HF_SPACE_REPO_ID=edbeeching/agentic-ui` for prod.

For private/internal single-user Spaces only, you can optionally expose the agent-host token in the web UI copy command:

```bash
SWITCH_UNSAFE_EXPOSE_HOST_TOKEN=1
```

To connect an agent host to a Space:

```bash
uv -vv tool install --force --reinstall git+ssh://git@github.com/edbeeching/agentic-ui.git
export HF_TOKEN=<hf-token>
export SWITCH_DAEMON_TOKEN=<environment-specific-shared-secret>
switch host --hub https://<space-subdomain>.hf.space
```

### Cloud Agent Hosts

The Space UI can launch an agent host as a Hugging Face Job. The Space-side `HF_TOKEN` and `SWITCH_DAEMON_TOKEN` secrets are passed server-side to the job; they are not returned to the browser.

Optional Space variables:

```bash
SWITCH_HF_JOBS_NAMESPACE=edbeeching
SWITCH_HF_JOBS_DEFAULT_IMAGE=python:3.12
SWITCH_HF_JOBS_DEFAULT_FLAVOR=cpu-basic
SWITCH_HF_JOBS_DEFAULT_TIMEOUT=2h
```

The default image installs agentic-ui from the private Space repo and connects back to the hub. Images used for real sessions must also include Claude Code or Codex CLI and any credentials those tools require.

## Release Flow

1. Create a feature branch from `main`.
2. Open a PR into `main`.
3. Merge after CI passes; the dev Space deploys automatically.
4. Validate `https://edbeeching-agentic-ui-dev.hf.space`.
5. Open a PR from `main` into `prod`.
6. Merge after CI passes; the production Space deploys automatically.

The GitHub workflow `Deploy HF Space` selects the Space target from the branch that passed CI:

- `main` deploys to `edbeeching/agentic-ui-dev`.
- `prod` deploys to `edbeeching/agentic-ui`.

The workflow uses the GitHub Actions repository secret `HF_TOKEN` to upload to both Spaces.

## CLI Reference

```text
switch hub    [-p PORT] [--host HOST] [--local-agent-host] [--allow-insecure] [-v]
switch host   [--hub URL] [--token TOKEN] [--hf-token TOKEN] [-n NAME] [-v]
switch daemon Backward-compatible alias for switch host
switch update Update the installed tool from the private repo
```

## Development

```bash
git clone git@github.com:edbeeching/agentic-ui.git
cd agentic-ui
uv tool install --force --editable .
```

This links the `switch` command to your local checkout. Python changes take effect immediately.

Run the all-in-one local dev command:

```bash
switch dev
```

Rebuild the production web bundle after frontend changes:

```bash
cd switch/web
npm install
npm run build
cp -r dist/* ../hub/static/
```

Run checks before opening a PR:

```bash
uv run --frozen pytest
cd switch/web && npm run lint && npm run build
diff -qr switch/web/dist switch/hub/static
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

## Security Notes

- Keep dev and prod `SWITCH_DAEMON_TOKEN` values separate.
- Do not expose `SWITCH_UNSAFE_EXPOSE_HOST_TOKEN=1` outside trusted private single-user Spaces.
- Cloud agent hosts are intentionally powerful; only launch trusted images with the credentials needed for the intended work.
- See [SECURITY.md](SECURITY.md) for the current security posture and reporting guidance.
