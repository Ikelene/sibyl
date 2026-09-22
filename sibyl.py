import asyncio
import base64
import json
import os
import random
import re
import tempfile
import threading
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ModuleNotFoundError:
    pass

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "chatgpt").lower()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
BOT_NAME = os.getenv("BOT_NAME", "SIBYL")
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "You are Sibyl, a helpful conversational AI assistant built for Discord. Be clear, natural, concise, and thoughtful. Adapt to the conversation without pretending to perform actions you cannot perform. Never ping users or roles.")
STATE_FILE = os.getenv("STATE_FILE", "sibyl_state.json")
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "30"))
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "1200"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.8"))
REPLY_MODE = os.getenv("REPLY_MODE", "mention").lower()
RANDOM_REPLY_CHANCE = float(os.getenv("RANDOM_REPLY_CHANCE", "0.08"))
ALLOWED_CHANNEL_IDS = {int(value) for value in os.getenv("ALLOWED_CHANNEL_IDS", "").split(",") if value.strip().isdigit()}
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "90"))
MAX_ATTACHMENT_BYTES = int(os.getenv("MAX_ATTACHMENT_BYTES", "10000000"))
DISCORD_MESSAGE_LIMIT = 2000


def validate_provider(provider):
    value = provider.strip().lower()
    if value not in {"chatgpt", "gemini"}:
        raise ValueError("provider must be chatgpt or gemini")
    return value


def split_message(text, limit=DISCORD_MESSAGE_LIMIT):
    remaining = str(text)
    chunks = []
    while len(remaining) > limit:
        cut = limit
        newline = remaining.rfind("\n", 0, limit + 1)
        space = remaining.rfind(" ", 0, limit + 1)
        boundary = max(newline, space)
        if boundary > 0:
            cut = boundary + 1
        chunks.append(remaining[:cut])
        remaining = remaining[cut:]
    if remaining:
        chunks.append(remaining)
    return chunks or [""]


def strip_bot_mention(text, bot_id):
    return re.sub(rf"<@!?{int(bot_id)}>", "", text).strip()


def should_respond(is_dm, mentioned, replied_to_bot, mode, chance):
    if is_dm or mentioned or replied_to_bot:
        return True
    if mode == "every":
        return True
    if mode == "random":
        return random.random() < chance
    return False


def _openai_content(item):
    text = item.get("content", "")
    name = item.get("name")
    if name and item.get("role") == "user":
        text = f"{name}: {text}"
    images = item.get("images", [])
    if not images:
        return text
    content = [{"type": "text", "text": text or "Describe and respond to these images."}]
    for image in images:
        content.append({"type": "image_url", "image_url": {"url": f"data:{image['mime_type']};base64,{image['data']}"}})
    return content


def build_openai_payload(history, system_prompt, model):
    messages = [{"role": "system", "content": system_prompt}]
    for item in history:
        messages.append({"role": item["role"], "content": _openai_content(item)})
    return {"model": model, "messages": messages, "temperature": TEMPERATURE, "max_tokens": MAX_OUTPUT_TOKENS}


def build_gemini_payload(history, system_prompt):
    contents = []
    for item in history:
        text = item.get("content", "")
        if item.get("name") and item.get("role") == "user":
            text = f"{item['name']}: {text}"
        parts = [{"text": text or "Describe and respond to these images."}]
        for image in item.get("images", []):
            parts.append({"inlineData": {"mimeType": image["mime_type"], "data": image["data"]}})
        contents.append({"role": "model" if item["role"] == "assistant" else "user", "parts": parts})
    return {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {"temperature": TEMPERATURE, "maxOutputTokens": MAX_OUTPUT_TOKENS},
    }


class StateStore:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.data = {"sessions": {}, "settings": {}}
        self._load()

    def _load(self):
        with self.lock:
            if not self.path.exists():
                return
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data["sessions"] = loaded.get("sessions", {})
                    self.data["settings"] = loaded.get("settings", {})
            except (OSError, json.JSONDecodeError):
                self.data = {"sessions": {}, "settings": {}}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.data, ensure_ascii=False, indent=2)
        handle, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(payload)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def history(self, scope):
        with self.lock:
            return [dict(item) for item in self.data["sessions"].get(scope, [])]

    def append(self, scope, role, content, name=None):
        with self.lock:
            item = {"role": role, "content": str(content)}
            if name:
                item["name"] = str(name)
            session = self.data["sessions"].setdefault(scope, [])
            session.append(item)
            self.data["sessions"][scope] = session[-MAX_HISTORY_MESSAGES:]
            self._save()

    def clear(self, scope):
        with self.lock:
            self.data["sessions"][scope] = []
            self._save()

    def settings(self, scope):
        with self.lock:
            return dict(self.data["settings"].get(scope, {}))

    def set_setting(self, scope, key, value):
        with self.lock:
            self.data["settings"].setdefault(scope, {})[key] = value
            self._save()


class AIClient:
    async def chat(self, provider, history, system_prompt, model=None):
        provider = validate_provider(provider)
        if provider == "chatgpt":
            return await self._chatgpt(history, system_prompt, model or OPENAI_MODEL)
        return await self._gemini(history, system_prompt, model or GEMINI_MODEL)

    async def _chatgpt(self, history, system_prompt, model):
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        import aiohttp
        url = f"{OPENAI_BASE_URL.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, json=build_openai_payload(history, system_prompt, model)) as response:
                data = await response.json(content_type=None)
                if response.status >= 400:
                    raise RuntimeError(_api_error(data, response.status))
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not content:
            raise RuntimeError("ChatGPT returned an empty response")
        return content.strip()

    async def _gemini(self, history, system_prompt, model):
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        import aiohttp
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, params={"key": GEMINI_API_KEY}, json=build_gemini_payload(history, system_prompt)) as response:
                data = await response.json(content_type=None)
                if response.status >= 400:
                    raise RuntimeError(_api_error(data, response.status))
        candidates = data.get("candidates", [])
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        content = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        if not content:
            reason = data.get("promptFeedback", {}).get("blockReason")
            raise RuntimeError(f"Gemini returned an empty response{f': {reason}' if reason else ''}")
        return content.strip()


def _api_error(data, status):
    if isinstance(data, dict):
        error = data.get("error", data)
        if isinstance(error, dict):
            message = error.get("message")
            if message:
                return f"API error {status}: {message}"
    return f"API error {status}"


def create_bot():
    import discord
    from discord import app_commands

    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = False
    store = StateStore(STATE_FILE)
    ai = AIClient()

    class SibylBot(discord.Client):
        def __init__(self):
            super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
            self.tree = app_commands.CommandTree(self)

        async def setup_hook(self):
            await self.tree.sync()

    bot = SibylBot()

    def conversation_scope(message):
        if message.guild:
            return f"guild:{message.guild.id}:channel:{message.channel.id}"
        return f"dm:{message.author.id}"

    def configuration_scope(source):
        guild = getattr(source, "guild", None)
        user = getattr(source, "user", None) or getattr(source, "author", None)
        return f"guild:{guild.id}" if guild else f"dm:{user.id}"

    def effective_settings(source):
        values = store.settings(configuration_scope(source))
        provider = values.get("provider", DEFAULT_PROVIDER)
        return {
            "provider": provider,
            "model": values.get("model", OPENAI_MODEL if provider == "chatgpt" else GEMINI_MODEL),
            "reply_mode": values.get("reply_mode", REPLY_MODE),
            "system_prompt": values.get("system_prompt", SYSTEM_PROMPT),
        }

    def can_configure(interaction):
        if OWNER_ID and interaction.user.id == OWNER_ID:
            return True
        permissions = getattr(interaction.user, "guild_permissions", None)
        return bool(permissions and permissions.manage_guild)

    async def deny_configuration(interaction):
        await interaction.response.send_message("manage server permission required", ephemeral=True)

    async def download_images(attachments):
        images = []
        for attachment in attachments:
            mime_type = attachment.content_type or ""
            if not mime_type.startswith("image/") or attachment.size > MAX_ATTACHMENT_BYTES:
                continue
            raw = await attachment.read()
            images.append({"mime_type": mime_type, "data": base64.b64encode(raw).decode("ascii")})
        return images

    async def generate_for(message, prompt):
        scope = conversation_scope(message)
        settings = effective_settings(message)
        images = await download_images(message.attachments)
        user_item = {"role": "user", "content": prompt, "name": message.author.display_name}
        if images:
            user_item["images"] = images
        history = store.history(scope)
        history.append(user_item)
        response = await ai.chat(settings["provider"], history, settings["system_prompt"], settings["model"])
        store.append(scope, "user", prompt, message.author.display_name)
        store.append(scope, "assistant", response)
        return response

    async def send_response(message, prompt):
        async with message.channel.typing():
            response = await generate_for(message, prompt)
        for chunk in split_message(response):
            await message.reply(chunk, mention_author=False, allowed_mentions=discord.AllowedMentions.none())

    @bot.event
    async def on_ready():
        await bot.change_presence(activity=discord.CustomActivity(name=f"{BOT_NAME} online"))
        print(f"{BOT_NAME} connected as {bot.user} ({bot.user.id})")

    @bot.event
    async def on_message(message):
        if message.author.bot or not bot.user:
            return
        is_dm = message.guild is None
        if not is_dm and ALLOWED_CHANNEL_IDS and message.channel.id not in ALLOWED_CHANNEL_IDS:
            return
        mentioned = bot.user in message.mentions
        replied_to_bot = False
        if message.reference:
            resolved = message.reference.resolved
            if resolved is None and message.reference.message_id:
                try:
                    resolved = await message.channel.fetch_message(message.reference.message_id)
                except discord.DiscordException:
                    resolved = None
            replied_to_bot = bool(resolved and getattr(resolved.author, "id", None) == bot.user.id)
        settings = effective_settings(message)
        if not should_respond(is_dm, mentioned, replied_to_bot, settings["reply_mode"], RANDOM_REPLY_CHANCE):
            return
        prompt = strip_bot_mention(message.content, bot.user.id)
        if not prompt and not any((attachment.content_type or "").startswith("image/") for attachment in message.attachments):
            prompt = "Respond naturally to me."
        try:
            await send_response(message, prompt)
        except Exception as error:
            await message.reply(f"provider failure: {error}", mention_author=False, allowed_mentions=discord.AllowedMentions.none())

    @bot.tree.command(name="ask", description="Ask the AI directly")
    @app_commands.describe(prompt="What you want to say")
    async def ask(interaction, prompt: str):
        await interaction.response.defer(thinking=True)
        settings = effective_settings(interaction)
        scope = f"guild:{interaction.guild_id}:channel:{interaction.channel_id}" if interaction.guild_id else f"dm:{interaction.user.id}"
        history = store.history(scope)
        history.append({"role": "user", "content": prompt, "name": interaction.user.display_name})
        try:
            response = await ai.chat(settings["provider"], history, settings["system_prompt"], settings["model"])
            store.append(scope, "user", prompt, interaction.user.display_name)
            store.append(scope, "assistant", response)
            chunks = split_message(response)
            await interaction.followup.send(chunks[0], allowed_mentions=discord.AllowedMentions.none())
            for chunk in chunks[1:]:
                await interaction.followup.send(chunk, allowed_mentions=discord.AllowedMentions.none())
        except Exception as error:
            await interaction.followup.send(f"provider failure: {error}", ephemeral=True)

    @bot.tree.command(name="provider", description="Choose ChatGPT or Gemini")
    @app_commands.choices(provider=[app_commands.Choice(name="ChatGPT", value="chatgpt"), app_commands.Choice(name="Gemini", value="gemini")])
    async def provider(interaction, provider: app_commands.Choice[str]):
        if not can_configure(interaction):
            await deny_configuration(interaction)
            return
        value = validate_provider(provider.value)
        store.set_setting(configuration_scope(interaction), "provider", value)
        store.set_setting(configuration_scope(interaction), "model", OPENAI_MODEL if value == "chatgpt" else GEMINI_MODEL)
        await interaction.response.send_message(f"provider set to {value}", ephemeral=True)

    @bot.tree.command(name="model", description="Set the model name for the active provider")
    async def model(interaction, model: str):
        if not can_configure(interaction):
            await deny_configuration(interaction)
            return
        store.set_setting(configuration_scope(interaction), "model", model.strip())
        await interaction.response.send_message(f"model set to {model.strip()}", ephemeral=True)

    @bot.tree.command(name="reply_mode", description="Choose when the bot replies")
    @app_commands.choices(mode=[app_commands.Choice(name="Mentions and replies", value="mention"), app_commands.Choice(name="Every message", value="every"), app_commands.Choice(name="Occasionally", value="random")])
    async def reply_mode(interaction, mode: app_commands.Choice[str]):
        if not can_configure(interaction):
            await deny_configuration(interaction)
            return
        store.set_setting(configuration_scope(interaction), "reply_mode", mode.value)
        await interaction.response.send_message(f"reply mode set to {mode.value}", ephemeral=True)

    @bot.tree.command(name="system_prompt", description="Set the server or DM personality prompt")
    async def system_prompt(interaction, prompt: str):
        if not can_configure(interaction):
            await deny_configuration(interaction)
            return
        store.set_setting(configuration_scope(interaction), "system_prompt", prompt.strip())
        await interaction.response.send_message("system prompt updated", ephemeral=True)

    @bot.tree.command(name="clear", description="Clear this channel's conversation history")
    async def clear(interaction):
        scope = f"guild:{interaction.guild_id}:channel:{interaction.channel_id}" if interaction.guild_id else f"dm:{interaction.user.id}"
        store.clear(scope)
        await interaction.response.send_message("conversation cleared", ephemeral=True)

    @bot.tree.command(name="status", description="Show the active AI configuration")
    async def status(interaction):
        settings = effective_settings(interaction)
        configured = bool(OPENAI_API_KEY if settings["provider"] == "chatgpt" else GEMINI_API_KEY)
        text = f"provider: {settings['provider']}\nmodel: {settings['model']}\nreply mode: {settings['reply_mode']}\napi key configured: {'yes' if configured else 'no'}"
        await interaction.response.send_message(text, ephemeral=True)

    return bot


def main():
    validate_provider(DEFAULT_PROVIDER)
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN is not configured")
    create_bot().run(DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
