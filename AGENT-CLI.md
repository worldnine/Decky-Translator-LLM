# Decky Agent CLI

A CLI for external AI agents and scripts to read the Steam Deck screen.

## Setup

Bundled with the Decky Translator plugin. No additional installation required.

```bash
# SSH into your Steam Deck
ssh deck@<YOUR_DECK_IP>

# Navigate to the plugin directory
cd ~/homebrew/plugins/decky-translator-llm

# Verify it works
python3 decky-agent-cli capabilities --json
```

## Security

Agent CLI is **disabled** by default.  
To enable it, go to Decky Translator settings and turn on the **Agent CLI** toggle.  
When disabled, all CLI operations, notifications, and RPC calls are rejected.

## Subcommands

### `capture` — Take a screenshot

```bash
python3 decky-agent-cli capture \
  --purpose "gameplay assist: check screen" \
  --json
```

| Option | Required | Description |
|--------|----------|-------------|
| `--purpose` | Yes | Purpose of capture (shown in notification) |
| `--app-name` | No | App name (used in filename) |
| `--notify` | No | Notification mode: `dot` / `thumbnail` / `message` (default: `thumbnail`) |
| `--json` | No | Output in JSON format |

Response example:
```json
{
  "ok": true,
  "action": "capture",
  "purpose": "gameplay assist: check screen",
  "captured_at": "2026-04-04T21:15:10+09:00",
  "image": {
    "path": "/tmp/decky-translator/Game_2026-04-04_21-15-10_abc12345.png",
    "base64": "data:image/png;base64,..."
  }
}
```

### `translate` — Translate screen text

```bash
python3 decky-agent-cli translate \
  --purpose "gameplay assist: translate UI" \
  --target ja \
  --json
```

| Option | Required | Description |
|--------|----------|-------------|
| `--purpose` | Yes | Purpose of capture |
| `--target` | No | Target language code (default: from settings) |
| `--input` | No | Input language code (default: auto) |
| `--notify` | No | Notification mode (default: `thumbnail`) |

### `describe` — Describe screen (gameplay assist)

```bash
python3 decky-agent-cli describe \
  --purpose "gameplay assist: check dialogue" \
  --prompt "Summarize the current objectives" \
  --json
```

| Option | Required | Description |
|--------|----------|-------------|
| `--purpose` | Yes | Purpose of capture |
| `--prompt` | No | Additional instruction prompt |
| `--notify` | No | Notification mode (default: `thumbnail`) |

Response example:
```json
{
  "ok": true,
  "action": "describe",
  "description": {
    "summary": "Mansion hallway with a chandelier in the center.",
    "objectives": ["Head to the northeast tower"],
    "ui": ["HP 320/450"],
    "notable_text": ["open only in the event of my death"]
  }
}
```

### `game` — Get running game info

```bash
python3 decky-agent-cli game --json
```

### `prompt` — Read/write prompts

```bash
# Get common prompt (raw text output)
python3 decky-agent-cli prompt get

# Get common prompt (JSON)
python3 decky-agent-cli prompt get --json

# Set common prompt
python3 decky-agent-cli prompt set --content "Group nearby text lines..."

# Set from stdin (for longer prompts)
cat my-prompt.txt | python3 decky-agent-cli prompt set --stdin

# Get game-specific prompt
python3 decky-agent-cli prompt get --app-id 12345

# Set game-specific prompt
python3 decky-agent-cli prompt set --app-id 12345 --stdin < game-prompt.txt
```

| Option | Required | Description |
|--------|----------|-------------|
| `get` / `set` | Yes | Action to perform |
| `--app-id` | No | Game App ID (omit for common prompt) |
| `--content` | No | Prompt content (for `set`) |
| `--stdin` | No | Read content from stdin (for `set`) |

### `capabilities` — List available commands

```bash
python3 decky-agent-cli capabilities --json
```

## Notification Modes

Control on-screen notifications with `--notify`:

| Mode | Display | Use case |
|------|---------|----------|
| `dot` | Red dot only | Minimal presence indicator |
| `thumbnail` | Screenshot thumbnail | See what was captured (default) |
| `message` | Purpose text | See why it was captured |

Notifications only appear when the Decky plugin is running.  
The CLI works normally without the plugin (notifications are silently skipped).

## SSH Usage

```bash
# Via Tailscale
ssh deck@steamdeck "cd ~/homebrew/plugins/decky-translator-llm && \
  python3 decky-agent-cli describe --purpose 'gameplay assist' --json"

# Via local network
ssh deck@<YOUR_DECK_IP> "cd ~/homebrew/plugins/decky-translator-llm && \
  python3 decky-agent-cli capture --purpose 'screen check' --json"
```

## Errors

Errors are returned as structured JSON when using `--json`:

```json
{
  "ok": false,
  "action": "describe",
  "error": {
    "code": "capture_failed",
    "message": "Failed to capture screenshot"
  }
}
```

| Exit code | Meaning |
|-----------|---------|
| 0 | Success |
| 1 | Runtime error |
| 2 | Argument error |
| 3 | Configuration / communication error |

## Read-Only

Agent CLI is read-only. It does not perform any game input or system modifications.
