# Herdr Port Roadmap

This note tracks Herdr-inspired features that fit hf-agent-ui's hub, daemon, and web-terminal architecture.

## Implemented First

- Agent state rollups: sessions carry `blocked`, `working`, `done`, `idle`, or `unknown` state so the sidebar can surface sessions needing attention without replacing the existing detailed `needs_input` fields.
- Session actions: sidebar context menu supports rename, duplicate, copy path, and close.
- Git/worktree badges: session rows can show branch, dirty state, ahead/behind counts, and managed worktree status when the daemon can probe Git metadata.

## Later Candidates

- Public automation API for `session.read`, `session.wait_for_output`, `session.wait_for_state`, `session.send_input`, and event subscriptions.
- Side-by-side terminal panes for comparing multiple agents or branches in one project view.
- Direct CLI attach for streaming a managed session into a local terminal.
- Broader agent registry and detection for tools beyond Claude, Codex, and Bash.
- Multi-client input ownership with read-only subscribers and explicit takeover.

## Non-Goals

- Do not port Herdr's Rust terminal renderer; hf-agent-ui should keep xterm.js in the browser.
- Do not port Herdr's TUI layout or keybinding model directly; web workflows should remain web-native.
