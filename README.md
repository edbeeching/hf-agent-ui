---
title: hf-agent-ui
sdk: docker
app_port: 7860
fullWidth: true
header: mini
---

# hf-agent-ui

Browser control for AI coding sessions. hf-agent-ui manages Claude Code and Codex CLI sessions across local machines, remote servers, and cloud/container agent hosts from one web UI.

## Architecture

```text
Browser <--WS--> Hub (FastAPI) <--WS--> Agent host (Python) <--stdio--> Claude / Codex CLI
```

- **Hub**: central FastAPI server, browser UI, agent-host registry, and WebSocket relay.
- **Agent host**: process running on a local, remote, or container machine. It starts Claude/Codex sessions and connects outbound to the hub.

## Install

Install from the GitHub repository with `uv`:

```bash
uv -vv tool install --force --reinstall git+https://github.com/edbeeching/hf-agent-ui.git
```

If you previously installed the project as `switch`, remove the old tool and use the new command name:

```bash
uv tool uninstall switch
uv -vv tool install --force --reinstall git+https://github.com/edbeeching/hf-agent-ui.git
hf-agent-ui --help
```

Update an installed copy:

```bash
hf-agent-ui update
```

## Quick Start

Start the hub:

```bash
hf-agent-ui hub
```

Open `http://localhost:9341`.

For single-machine development or debugging, start the hub with a local agent host:

```bash
hf-agent-ui hub --local-agent-host
```

To connect another machine to a hub:

```bash
hf-agent-ui host --hub http://<hub-host>:9341
```

By default `hf-agent-ui hub` binds to `127.0.0.1`. To expose it on a network interface, configure browser auth first:

```bash
export HF_AGENT_UI_BROWSER_TOKEN=<browser-token>
hf-agent-ui hub --host 0.0.0.0
```

Open the UI once with:

```text
http://<hub-host>:9341/#uiToken=<browser-token>
```

`--allow-insecure` can be used for trusted local-network experiments, but it exposes browser control of connected agent hosts.

## Environments

| Environment | Branch | Space | URL | Deploy behavior |
|-------------|--------|-------|-----|-----------------|
| Development | `main` | `edbeeching/hf-agent-ui-dev` | `https://edbeeching-hf-agent-ui-dev.hf.space` | Auto-deploy after `main` CI passes |
| Production | `prod` | `edbeeching/hf-agent-ui` | `https://edbeeching-hf-agent-ui.hf.space` | Manual deploy from `prod` with explicit production confirmation |

Feature work should land through PRs into `main`. Production release candidates should be PRs from `main` into `prod` after the dev Space has been validated.

Production deploys are not automatic: the deploy workflow must be run manually from `prod` with `target=production` and the exact confirmation phrase `deploy production`.

## Hugging Face Spaces

Both Spaces are private Docker Spaces using the front matter at the top of this README:

```yaml
sdk: docker
app_port: 7860
```

Each Space needs:

```bash
HF_AGENT_UI_HOST_TOKEN=<environment-specific-shared-secret>
HF_TOKEN=<hf-token-with-space-and-jobs-access>
```

Each Space also needs:

```bash
HF_AGENT_UI_TRUST_PROXY_AUTH=1
HF_AGENT_UI_SPACE_REPO_ID=<space-repo-id>
```

Use `HF_AGENT_UI_SPACE_REPO_ID=edbeeching/hf-agent-ui-dev` for dev and `HF_AGENT_UI_SPACE_REPO_ID=edbeeching/hf-agent-ui` for prod.

For private/internal single-user Spaces only, you can optionally expose the agent-host token in the web UI copy command:

```bash
HF_AGENT_UI_UNSAFE_EXPOSE_HOST_TOKEN=1
```

To connect an agent host to a Space:

```bash
uv -vv tool install --force --reinstall git+https://github.com/edbeeching/hf-agent-ui.git
export HF_TOKEN=<hf-token>
export HF_AGENT_UI_HOST_TOKEN=<environment-specific-shared-secret>
hf-agent-ui host --hub https://<space-subdomain>.hf.space
```

The public Space names are:

```text
Development: https://edbeeching-hf-agent-ui-dev.hf.space
Production:  https://edbeeching-hf-agent-ui.hf.space
```

The older `edbeeching-agentic-ui*.hf.space` URLs were renamed and should not be used for new host connections.

### Cloud Agent Hosts

The Space UI can launch an agent host as a Hugging Face Job. The Space-side `HF_TOKEN` and `HF_AGENT_UI_HOST_TOKEN` secrets are passed server-side to the job; they are not returned to the browser.

Optional Space variables:

```bash
HF_AGENT_UI_JOBS_NAMESPACE=edbeeching
HF_AGENT_UI_JOBS_DEFAULT_IMAGE=python:3.12
HF_AGENT_UI_JOBS_DEFAULT_FLAVOR=cpu-basic
HF_AGENT_UI_JOBS_DEFAULT_TIMEOUT=2h
```

The default image installs hf-agent-ui from the configured Space snapshot and connects back to the hub. Images used for real sessions must also include Claude Code or Codex CLI and any credentials those tools require.

## Release Flow

1. Create a feature branch from `main`.
2. Open a PR into `main`.
3. Merge after CI passes; the dev Space deploys automatically.
4. Validate `https://edbeeching-hf-agent-ui-dev.hf.space`.
5. Open a PR from `main` into `prod`.
6. Merge after CI passes.
7. Manually run `Deploy HF Space` from the `prod` branch.
8. Set `target=production` and `confirm_production=deploy production`.

The GitHub workflow `Deploy HF Space` selects the Space target from the branch that passed CI:

- successful `main` push CI deploys to `edbeeching/hf-agent-ui-dev`.
- manual confirmed `prod` workflow runs deploy to `edbeeching/hf-agent-ui`.

The workflow uses the GitHub Actions repository secret `HF_TOKEN` to upload to both Spaces.

## CLI Reference

```text
hf-agent-ui hub    [-p PORT] [--host HOST] [--local-agent-host] [--allow-insecure] [-v]
hf-agent-ui host   [--hub URL] [--token TOKEN] [--hf-token TOKEN] [-n NAME] [-v]
hf-agent-ui update Update the installed tool from the GitHub repo
```

## Development

```bash
git clone https://github.com/edbeeching/hf-agent-ui.git
cd hf-agent-ui
uv tool install --force --editable .
```

This links the `hf-agent-ui` command to your local checkout. Python changes take effect immediately.

Run the all-in-one local dev command:

```bash
hf-agent-ui dev
```

Rebuild the production web bundle after frontend changes:

```bash
cd hf_agent_ui/web
npm install
npm run build
cp -r dist/* ../hub/static/
```

Run checks before opening a PR:

```bash
uv run --frozen pytest
cd hf_agent_ui/web && npm run lint && npm run build
diff -qr hf_agent_ui/web/dist hf_agent_ui/hub/static
```

### Worktrees

Keep local worktrees inside the repo under `.worktrees/` so sandboxed coding agents can read and write them without needing permissions for sibling directories:

```bash
mkdir -p .worktrees
git worktree add .worktrees/<name> -b <branch> origin/main
```

The `.worktrees/` directory is ignored by Git. Avoid placing worktrees next to the repo, such as `../hf-agent-ui-main`, because those paths may sit outside an agent's writable workspace root.

## Supported Tools

| Tool | Status | Notes |
|------|--------|-------|
| Claude Code | Supported | Full bidirectional streaming via stream-json |
| Codex CLI | Supported | Fire-and-forget exec with resume for follow-ups |

## Security Notes

- Keep dev and prod `HF_AGENT_UI_HOST_TOKEN` values separate.
- Do not expose `HF_AGENT_UI_UNSAFE_EXPOSE_HOST_TOKEN=1` outside trusted private single-user Spaces.
- Cloud agent hosts are intentionally powerful; only launch trusted images with the credentials needed for the intended work.
- See [SECURITY.md](SECURITY.md) for the current security posture and reporting guidance.
