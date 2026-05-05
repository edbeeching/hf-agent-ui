# agentic-ui — User Stories

## 1. Solo developer, single machine

**Scenario:** You're working on a project and want a web UI to interact with Claude Code instead of the terminal.

```bash
# Install
uv tool install git+ssh://git@github.com/edbeeching/agentic-ui.git

# Start everything
switch hub &
switch host &

# Open http://localhost:9341
# Click "+" next to the environment → select "Claude Code" → set working dir → Create
# Type a message in the input bar → see streaming response
```

---

## 2. Multiple projects, multiple sessions

**Scenario:** You're juggling work across 3 repos and want all sessions visible at once.

```
Sidebar:
  local (PC)
    ● [claude] ~/work/frontend      ← working on React components
    ● [claude] ~/work/api            ← debugging a FastAPI endpoint
    ● [codex]  ~/work/infra          ← Codex fixing Terraform configs
```

Click any session to see its conversation. Move between them instantly. Each session runs independently — Claude Code in two of them, Codex in the third.

---

## 3. Remote dev server

**Scenario:** You SSH into a GPU server to run ML training. You want Claude Code there, controlled from your laptop's browser.

```bash
# On your laptop — start the hub
switch hub

# On the remote server — install and connect back
uv tool install git+ssh://git@github.com/edbeeching/agentic-ui.git
switch host --hub http://your-laptop:9341 --name gpu-server
```

```
Sidebar:
  local (laptop)
    ● [claude] ~/work/agentic-ui
  gpu-server (ml-box)
    ● [claude] ~/experiments/train    ← running on the remote machine
```

Both agent hosts appear in the same dashboard. You create sessions on either machine from the same browser tab.

---

## 4. Docker development environment

**Scenario:** Your dev environment runs inside Docker containers. You want Claude Code inside the container, controlled from outside.

```bash
# On host — start the hub
switch hub

# Inside the container
pip install uv  # or however you get uv in there
uv tool install git+ssh://git@github.com/edbeeching/agentic-ui.git
switch host --hub http://host.docker.internal:9341 --name my-container
```

The container's agent host registers with your host's hub. You create sessions that run inside the container's filesystem.

---

## 5. Comparing Claude Code vs Codex on the same task

**Scenario:** You want to see how both tools approach the same bug fix.

```
Sidebar:
  local (PC)
    ● [claude] ~/work/myapp          ← "fix the login bug in auth.py"
    ● [codex]  ~/work/myapp          ← same prompt, same repo
```

Create two sessions on the same working directory — one Claude Code, one Codex. Send the same prompt to each. Compare their approaches side by side by clicking between them.

---

## 6. Dev workflow with hot reload

**Scenario:** You're actively developing agentic-ui itself and want instant feedback.

```bash
# One command starts everything with hot reload
switch dev

# Or manually:
switch hub --dev    # Python auto-reload via uvicorn
cd switch/web && npm run dev   # Frontend hot reload via Vite
switch host

# Or run the hub with a local agent host attached:
switch hub --local-agent-host
```

- Edit Python files → hub auto-restarts
- Edit React files → browser hot-reloads
- Open http://localhost:5173 (Vite dev server)

---

## 7. Team setup (future)

**Scenario:** Your team shares a central hub. Each developer runs an agent host on their machine.

```bash
# Ops: deploy the hub on a shared server
switch hub --host 0.0.0.0 --port 9341

# Each developer:
switch host --hub http://hub.internal:9341 --name alice-laptop
switch host --hub http://hub.internal:9341 --name bob-workstation
```

```
Sidebar:
  alice-laptop (alice-mbp)
    ● [claude] ~/code/frontend
  bob-workstation (bob-pc)
    ● [claude] ~/code/backend
    ● [codex]  ~/code/backend
```

Everyone sees all sessions. (Auth not yet implemented — single-user trust model for now.)

---

## 8. Self-updating

**Scenario:** A new version of agentic-ui is pushed to the repo.

```bash
switch update
# → pulls latest from GitHub, reinstalls the tool
# Restart hub/agent host to pick up changes
```

---

## Interaction flow (what happens under the hood)

```
1. User clicks "+" next to an environment in the sidebar
2. Browser sends:  { type: "pty.create", daemonId, workDir, tool: "claude" }
3. Hub relays to the agent host via WebSocket
4. Agent host spawns: claude in a pseudo-terminal
5. Agent host subscribes hub to session events
6. Hub sends back: { type: "pty.created", session: { id, status, tool, mode: "pty", ... } }
7. Session appears in sidebar

8. User types into the xterm terminal
9. Browser sends:  { type: "pty.input", daemonId, sessionId, data }
10. Hub relays to the agent host
11. Agent host writes keystrokes to the PTY
12. Claude/Codex streams terminal output → agent host emits pty.output → hub relays to browser
13. Browser renders the full TUI in xterm
14. If the agent needs approval/auth/confirmation, agent host emits session.input_required and the sidebar marks the session
15. When the user types into that session, agent host emits session.input_resolved and the marker clears

16. If the browser refreshes, it sends session.list to each agent host and restores live sessions in the sidebar
17. When the user selects a restored session, browser sends session.subscribe and the agent host returns recent ptyOutput for replay

18. User clicks stop on the session
19. Browser sends:  { type: "session.stop", daemonId, sessionId }
20. Agent host sends SIGTERM to Claude process
21. Session exits, status updates to "stopped"
```
