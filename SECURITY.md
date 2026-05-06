# Security Policy

## Supported Versions

agentic-ui is pre-release software. Security fixes target the `main` branch until versioned releases are established.

## Threat Model

agentic-ui is a trusted-admin control plane for local and remote AI coding sessions. Anyone with browser access to the hub can potentially control connected agent hosts, send terminal input, and view terminal output. Do not expose the hub to untrusted users.

For local use, `switch hub` binds to `127.0.0.1` by default. For network use, configure `SWITCH_UI_TOKEN` or run behind a trusted private access layer and set `SWITCH_TRUST_PROXY_AUTH=1`. Browser tokens should be bootstrapped with `#uiToken=...` so they are not sent in HTTP request URLs.

Custom launch commands intentionally execute shell commands on the selected agent host. Treat them as arbitrary code execution by the authenticated UI user.

Cloud agent hosts launched through Hugging Face Jobs receive server-side secrets needed to connect back to the hub. Only enable this feature for trusted-admin hubs and use tokens scoped for the intended namespace.

## Reporting a Vulnerability

Before public release, report vulnerabilities directly to the repository owner. After public release, use GitHub private vulnerability reporting if it is enabled for the repository.

Do not include live tokens, private session output, or other secrets in public issues.
