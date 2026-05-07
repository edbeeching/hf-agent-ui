# Contributing

Thanks for considering a contribution to hf-agent-ui.

## Development

Install the project from a checkout:

```bash
uv tool install --force --editable .
```

Run the local development stack:

```bash
hf-agent-ui dev
```

Run the main checks before opening a pull request:

```bash
uv run --frozen pytest
cd hf_agent_ui/web
npm install
npm run lint
npm run build
cd ../..
diff -qr hf_agent_ui/web/dist hf_agent_ui/hub/static
```

## Pull Requests

- Open pull requests against `main`.
- Keep changes focused and include tests for behavior changes.
- Rebuild and commit `hf_agent_ui/hub/static` when changing the frontend.
- Do not include live tokens, private session output, local machine credentials, or cluster-specific secrets.

Production deploys are intentionally manual and must not be triggered without explicit maintainer approval.
