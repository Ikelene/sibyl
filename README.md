<p align="center">
  <img src="assets/sibyl.svg" alt="Sibyl" width="900">
</p>

<p align="center">
  <strong>A standalone Discord AI chatbot with memory, image understanding, and two providers.</strong>
</p>

<p align="center">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="discord.py" src="https://img.shields.io/badge/discord.py-2.x-5865F2?style=flat-square&logo=discord&logoColor=white">
  <img alt="ChatGPT" src="https://img.shields.io/badge/provider-ChatGPT-10A37F?style=flat-square&logo=openai&logoColor=white">
  <img alt="Gemini" src="https://img.shields.io/badge/provider-Gemini-4285F4?style=flat-square&logo=googlegemini&logoColor=white">
  <img alt="MIT License" src="https://img.shields.io/badge/license-MIT-87f7d0?style=flat-square">
</p>

# Sibyl

Sibyl is a compact, self-hosted Discord AI chatbot. Connect a Discord token, choose ChatGPT or Gemini, and give each server its own provider, model, reply mode, and personality.

No dashboard. No external database. No framework surrounding the framework.

The banner is hand-authored ASCII artwork rendered as SVG. No generated imagery is used.

## Features

- ChatGPT and Gemini API-key providers
- Per-server provider, model, reply mode, and system prompt
- Persistent conversation history per channel or DM
- Mentions, replies, DMs, every-message mode, and occasional replies
- Image understanding for Discord attachments
- Discord-safe message splitting
- Slash commands with permission checks
- Suppressed user and role pings in AI output
- Atomic JSON state writes
- One application file with configuration grouped at the top

## Requirements

- Python 3.10 or newer
- A Discord bot token
- An OpenAI API key, a Gemini API key, or both

## Quick start

```bash
git clone https://github.com/Ikelene/sibyl.git
cd sibyl
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Add your credentials to `.env`:

```env
DISCORD_TOKEN=your_discord_bot_token
OPENAI_API_KEY=your_openai_api_key
GEMINI_API_KEY=your_gemini_api_key
DEFAULT_PROVIDER=chatgpt
```

Start Sibyl:

```bash
python sibyl.py
```

All secret and configuration variables are declared together at the top of `sibyl.py`. Values are loaded from the environment, keeping credentials out of source control.

## Discord setup

1. Open the [Discord Developer Portal](https://discord.com/developers/applications).
2. Create an application and add a bot.
3. Enable **Message Content Intent** under **Bot → Privileged Gateway Intents**.
4. Generate an invite with the `bot` and `applications.commands` scopes.
5. Grant these permissions:
   - View Channels
   - Send Messages
   - Send Messages in Threads
   - Read Message History
   - Attach Files
   - Use Slash Commands
6. Invite the bot to your server.

## Providers

### ChatGPT

```env
DEFAULT_PROVIDER=chatgpt
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4.1-mini
```

`OPENAI_BASE_URL` defaults to `https://api.openai.com/v1` and can point to an OpenAI-compatible Chat Completions endpoint.

### Gemini

```env
DEFAULT_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash
```

Server managers can switch providers at runtime with `/provider`.

## Commands

- `/ask` sends a direct prompt.
- `/provider` selects ChatGPT or Gemini.
- `/model` changes the active model.
- `/reply_mode` selects mentions, every message, or occasional replies.
- `/system_prompt` changes the server or DM personality.
- `/clear` clears the current conversation.
- `/status` shows the active provider configuration.

Provider, model, reply mode, and system prompt changes require **Manage Server**. `OWNER_ID` grants the bot owner the same access everywhere.

## Reply modes

- `mention` replies in DMs, when mentioned, or when someone replies to Sibyl.
- `every` replies to every human message in an allowed channel.
- `random` always replies to mentions and replies, with occasional responses controlled by `RANDOM_REPLY_CHANCE`.

Restrict chat handling to specific channels with a comma-separated list:

```env
ALLOWED_CHANNEL_IDS=123456789012345678,234567890123456789
```

Leave it empty to allow every visible channel.

## State

Conversation history and server settings are stored in `sibyl_state.json` by default. Change the location with `STATE_FILE`.

Only text history is persisted. Image bytes are sent to the selected provider for the current request and are not written to state.

## Tests

```bash
python -m unittest discover -s tests -v
```

## systemd

```ini
[Unit]
Description=Sibyl Discord AI
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/sibyl
ExecStart=/opt/sibyl/.venv/bin/python /opt/sibyl/sibyl.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Security

Never commit real tokens. Keep them in `.env`, a secret manager, or service environment variables. Rotate any credential that reaches Git history.

## License

MIT
