# AI Debate Arena

> [한국어 README](README.ko.md)

A web app where Claude and Gemini debate each other in real time.

## Why This Project is Different

**No API credits required.** Most AI projects require paid API keys, which charge per token and add up quickly. This project is built entirely on top of standard consumer subscriptions:

- **Claude** is called via the Claude Code CLI — using your existing **Claude Pro plan** (the same $20/month subscription used for chatting), not the Anthropic API.
- **Gemini** is driven by browser automation against the Gemini web UI — using your existing **Google One AI Plus plan**, not the Gemini API.

If you already pay for Claude Pro and Google One AI Plus, you can run debates within your existing plan limits — at no additional cost.

## Overview

- **Claude**: Called via Claude Code CLI (uses Pro plan quota — no API key required)
- **Gemini**: Controlled via Naver Whale browser automation (uses Google One AI Plus subscription) or Gemini CLI
- **Real-time streaming**: Debate progress streamed live via SSE (Server-Sent Events)
- **Auto-save & resume**: Debates are saved automatically and can be continued with follow-up topics

## Debate Flow

1. **Research**: Gemini searches the web to gather data on the topic
2. **Opening statements**: Claude and Gemini each present their position
3. **Rebuttal rounds**: They debate for the configured number of rounds — each side **must directly address the opponent's specific claims**
4. **Conclusion**: Claude summarizes and synthesizes the full debate
5. **Save & continue**: Auto-saved on completion; resume with additional rounds or a deeper topic

> If Claude ends a response with `[RESEARCH_REQUEST]: ...`, Gemini will research the requested data and provide it.

## Requirements

- **Python 3.9+**
- **Claude Code CLI** — installed and logged in (`claude` command available)
- **Naver Whale browser** — logged into Google account at gemini.google.com (required only when using Gemini Web mode)
- **Gemini CLI** (`gemini`) — installed and authenticated (required only when using Gemini CLI models)

## Installation

```bash
git clone <repo>
cd debate-arena

pip install -r requirements.txt
```

## Running

```bash
python app.py
```

Open `http://localhost:5050` in your browser.

> When using Gemini Web mode, Whale browser must be **already running** and **logged into Gemini** before starting a debate.

## Usage

### Starting a debate

1. Enter a topic (e.g. `Will the US enter a recession in 2026?`)
2. Choose number of rounds (2–5)
3. Select Claude / Gemini models
4. Configure options (Anti-Anchoring, Sonnet Conclusion)
5. Click **Start Debate**

### Options

| Option | Description |
|--------|-------------|
| ⚓ Anti-Anchoring | Prevents models from anchoring on each other's framing |
| ⚡ Sonnet Conclusion | Uses `claude-sonnet-4-6` for the conclusion instead of the selected Claude model |

### Save & continue

- Debates are **auto-saved** when complete
- Click **▶ Additional Rounds** to continue the current debate
- Enter an optional deeper topic — previous context is preserved for both models
- Use **📁 Load saved debate** to view, resume, or delete past debates (paginated, 10 per page)

## Supported Models

### Claude
| Model | Notes |
|-------|-------|
| Claude Opus 4.8 | Default — most capable |
| Claude Opus 4.7 | |
| Claude Opus 4.6 | |
| Claude Sonnet 4.6 | |
| Claude Haiku 4.5 | Fastest |

### Gemini
| Model | Notes |
|-------|-------|
| Gemini (Web Browser) | Default — uses Whale browser automation |
| Gemini 3.1 Pro Preview (CLI) | Requires Gemini CLI |
| Gemini 3 Flash Preview (CLI) | Requires Gemini CLI |
| Gemini 2.5 Pro (CLI) | Requires Gemini CLI |
| Gemini 2.0 Flash (CLI) | Requires Gemini CLI |

## Anti-Hallucination

All models are instructed to:
- Only cite facts and figures from research material or verified knowledge
- Never fabricate statistics, prices, percentages, study names, or specific figures
- State "data not available" when specific data is missing rather than inventing numbers
- Directly address and rebut the opponent's specific claims — ignoring arguments is not allowed

## Project Structure

```
debate-arena/
├── app.py              # Starlette ASGI backend
├── templates/
│   └── index.html      # Frontend (SSE streaming UI)
├── debates/            # Saved debate JSON files
└── requirements.txt
```

## Tech Stack

| Layer | Details |
|-------|---------|
| Backend | Python, Starlette, Uvicorn |
| Frontend | Vanilla JS, SSE |
| Claude integration | Claude Code CLI (`claude -p --system-prompt`) |
| Gemini integration | Whale browser AppleScript (osascript) or Gemini CLI (`gemini -p`) |
| Encoding | Base64 (bypasses AppleScript → JS multi-layer escaping) |

## How the Gemini Browser Automation Works

JavaScript is injected directly into Whale's Gemini tab via AppleScript.

- Prompts are **Base64-encoded** and decoded with `atob()` + `decodeURIComponent()` to handle non-ASCII characters correctly
- Input and send happen in a **background tab** — the active tab is never disturbed
- Searches **all open windows** for the Gemini tab (not just the front window)
- Completion detection: response length polled every 2s; two identical readings in a row = done
- Response reading: split into 4,000-character chunks to work around AppleScript's return value size limit
- From round 2 onward, the **same Gemini tab is reused** to preserve conversation context

## Notes

- Claude Code CLI's **Pro plan hourly token limit** may interrupt long debates. The reset time is shown when this happens.
- If Gemini times out (180s for web, 120s for CLI), check your network or Gemini service status.
- When using Gemini CLI models, if capacity is exceeded, an error is shown — switch to a different model.
- Whale browser must stay open during automation — closing the Gemini tab mid-debate will cause an error.
