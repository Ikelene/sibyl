import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sibyl


class MessageHelpersTests(unittest.TestCase):
    def test_split_message_respects_discord_limit_and_preserves_text(self):
        text = "alpha\n" + ("x" * 4200) + "\nomega"
        chunks = sibyl.split_message(text, 2000)
        self.assertTrue(all(1 <= len(chunk) <= 2000 for chunk in chunks))
        self.assertEqual("".join(chunks), text)

    def test_strip_bot_mention_removes_both_discord_forms(self):
        self.assertEqual(sibyl.strip_bot_mention("hello <@123> and <@!123>", 123), "hello  and")

    def test_should_respond_in_dms(self):
        self.assertTrue(sibyl.should_respond(True, False, False, "mention", 0.0))

    def test_should_respond_to_mentions_and_replies(self):
        self.assertTrue(sibyl.should_respond(False, True, False, "mention", 0.0))
        self.assertTrue(sibyl.should_respond(False, False, True, "mention", 0.0))

    def test_every_mode_responds_to_every_human_message(self):
        self.assertTrue(sibyl.should_respond(False, False, False, "every", 0.0))

    def test_random_mode_uses_configured_chance(self):
        with patch("sibyl.random.random", return_value=0.2):
            self.assertTrue(sibyl.should_respond(False, False, False, "random", 0.25))
            self.assertFalse(sibyl.should_respond(False, False, False, "random", 0.1))


class StoreTests(unittest.TestCase):
    def test_store_persists_scoped_history_and_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = sibyl.StateStore(path)
            store.append("guild:channel", "user", "hello", "Ikelene")
            store.append("guild:channel", "assistant", "hi")
            reloaded = sibyl.StateStore(path)
            self.assertEqual([item["content"] for item in reloaded.history("guild:channel")], ["hello", "hi"])
            reloaded.clear("guild:channel")
            self.assertEqual(reloaded.history("guild:channel"), [])

    def test_store_limits_history(self):
        with tempfile.TemporaryDirectory() as directory:
            store = sibyl.StateStore(Path(directory) / "state.json")
            for index in range(sibyl.MAX_HISTORY_MESSAGES + 4):
                store.append("scope", "user", str(index))
            self.assertEqual(len(store.history("scope")), sibyl.MAX_HISTORY_MESSAGES)


class ProviderPayloadTests(unittest.TestCase):
    def test_openai_payload_contains_system_and_history(self):
        history = [{"role": "user", "content": "hello", "name": "Ikelene"}]
        payload = sibyl.build_openai_payload(history, "rules", "gpt-4.1-mini")
        self.assertEqual(payload["model"], "gpt-4.1-mini")
        self.assertEqual(payload["messages"][0], {"role": "system", "content": "rules"})
        self.assertIn("Ikelene: hello", payload["messages"][1]["content"])

    def test_gemini_payload_maps_assistant_to_model(self):
        history = [{"role": "assistant", "content": "hi"}, {"role": "user", "content": "hello"}]
        payload = sibyl.build_gemini_payload(history, "rules")
        self.assertEqual(payload["systemInstruction"]["parts"][0]["text"], "rules")
        self.assertEqual(payload["contents"][0]["role"], "model")
        self.assertEqual(payload["contents"][1]["role"], "user")


class ConfigurationTests(unittest.TestCase):
    def test_provider_validation_rejects_unknown_provider(self):
        with self.assertRaises(ValueError):
            sibyl.validate_provider("claude")

    def test_provider_validation_accepts_supported_providers(self):
        self.assertEqual(sibyl.validate_provider("chatgpt"), "chatgpt")
        self.assertEqual(sibyl.validate_provider("gemini"), "gemini")

    def test_default_branding_is_sibyl(self):
        self.assertEqual(sibyl.BOT_NAME, "SIBYL")
        self.assertEqual(sibyl.STATE_FILE, "sibyl_state.json")
        self.assertIn("helpful conversational AI assistant", sibyl.SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
