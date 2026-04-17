# Cursor IDE — HackerStation workflow

This repo is set up as a **Cursor-first** environment. Warp stays as your terminal; Cursor is the editor, debugger, and AI-assistant hub.

## One-time setup

```bash
# 1. Install Cursor (skip if already installed)
brew install --cask cursor

# 2. Install the 'cursor' shell command
# Open Cursor → Cmd+Shift+P → "Shell Command: Install 'cursor' command in PATH"

# 3. Open this repo
cursor ~/Desktop/Projects/hackerstation

# 4. Install the recommended extensions
# Cursor will prompt you — say yes. The list is in .vscode/extensions.json
```

## Wire Cursor's AI to your local Ollama (offline mode)

Cursor → **Settings → Models → Add model**:

| Field | Value |
|-------|-------|
| Provider | OpenAI-compatible |
| Base URL | `http://localhost:11434/v1` |
| Model | `hackerstation-code` |
| API key | `local-ollama` (anything non-empty; Ollama ignores it) |

Repeat for `hackerstation-reason` as a second model entry.

Switch models in the chat with **Cmd+/**.

**Caveat:** Cursor's "Tab" inline autocomplete currently requires Cursor's hosted model. If strict offline is a hard requirement, disable Tab in Settings → Features → Tab Completion.

## First 5 commands in Cursor

Open the integrated terminal (**Ctrl+`**) and run:

```bash
./start.sh status                                        # 1. is anything already up?
./start.sh all                                           # 2. boot Ollama + router + supervisor
curl -s http://localhost:8080/health | python3 -m json.tool   # 3. verify router
tail -f logs/self-heal.log                               # 4. (in a split pane) watch events
./start.sh lab                                           # 5. optional: start the Docker lab
```

Split the terminal with **Cmd+\\** to keep `tail` in one pane and a second shell in the other.

## Daily workflow

### Starting and stopping

| Action | Shortcut |
|--------|----------|
| Start full stack | **Cmd+Shift+B** (runs default build task: "HackerStation: start all") |
| Run any task | **Cmd+Shift+P → Run Task → pick one** |
| Stop everything | Task: "HackerStation: stop" |

Available tasks (`Cmd+Shift+P → Run Task`):
- HackerStation: start all
- HackerStation: status
- HackerStation: stop
- HackerStation: lab up (Docker)
- HackerStation: lab down
- HackerStation: tail self-heal log
- HackerStation: tail router.log
- HackerStation: health (curl /health)
- HackerStation: status (detailed)
- HackerStation: rebuild custom Ollama models
- HackerStation: update nuclei templates

### Debugging

- Open `router.py` → set a breakpoint → press **F5**.
- Cursor launches the router in debug mode via `.vscode/launch.json`.
- Console output goes to the integrated terminal.
- Make a request from another terminal: `curl -X POST http://localhost:8080/generate -d '{"prompt":"test"}'`. Breakpoint fires.

Compound config **"Router + Supervisor"** runs both at once.

### AI-assisted edits

- **Cmd+K** — inline edit with your local `hackerstation-code` model.
  Example: select `do_POST` → Cmd+K → "add a 413 if the body exceeds 32 KB".
- **Cmd+L** — chat panel with full-repo context.
- **`@file`** / **`@folder`** mentions scope the AI to specific files.

The project AI rules in `.cursor/rules` tell Cursor:
- Keep router.py stdlib-only.
- Default to loopback binding.
- Respect the 8 GB RAM budget.
- Never propose cloud API integrations.

Cursor applies these rules automatically to every chat and edit.

## What lives where

```
.cursor/
  settings.json    ← Cursor-specific editor settings (uses hackerstation-code by default)
  rules            ← project-level AI guardrails (8GB, stdlib-only, security posture)

.vscode/
  launch.json      ← F5 launch configs for router, supervisor, memory probe
  tasks.json       ← one-click shortcuts to ./start.sh and log tails
  extensions.json  ← recommended extensions (Python, Docker, YAML, etc.)
```

## Why Cursor over Warp for development

- **Warp is a terminal.** It has great split panes, blocks, and AI for shell commands. Keep it.
- **Cursor is an editor.** Multi-file refactors, inline AI edits, debugger, YAML/Python/Docker language support.
- **For this repo specifically:** `router.py` is ~600 lines of Python. Editing that in a terminal with `vim`/`nano` is slow. Cursor makes it 5× faster.

The two are complementary, not competitive. Use Cursor for code, Warp for running commands, `./start.sh` as the single entry point for system control.
