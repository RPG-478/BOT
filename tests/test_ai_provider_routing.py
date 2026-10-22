"""AGO BOT's command and model picker route DSH combos separately from Logfare."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]


def load_cog(name):
    # The runtime installs these files as Discord extensions. Loading by path also
    # avoids an unrelated site-packages package named ``cogs`` during unit tests.
    spec = importlib.util.spec_from_file_location(f"agobot_{name}", ROOT / "cogs" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Typing:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


class AiProviderRoutingTest(unittest.IsolatedAsyncioTestCase):
    async def test_ai_command_uses_combo_without_logfare_key(self):
        ai = load_cog("ai")
        ctx = SimpleNamespace(author=SimpleNamespace(id=123), typing=lambda: Typing(),
                              reply=AsyncMock())
        with patch.object(ai.ai_preferences, "get_model", return_value="combo:ago-free"), \
             patch.object(ai.dsh_gateway, "configured", return_value=True), \
             patch.object(ai.dsh_gateway, "chat", new_callable=AsyncMock,
                          return_value="DSHの回答") as chat, \
             patch.object(ai.logfare, "api_key", return_value=None), \
             patch.object(ai.logfare, "resolve_model", new_callable=AsyncMock) as resolve:
            await ai.AICog.ai.callback(ai.AICog(None), ctx, prompt="こんにちは")
        chat.assert_awaited_once()
        self.assertEqual(chat.await_args.args[0], "combo:ago-free")
        resolve.assert_not_awaited()
        embed = ctx.reply.await_args.kwargs["embed"]
        self.assertEqual(embed.description, "DSHの回答")

    async def test_picker_lists_logfare_and_dsh_combos(self):
        general = load_cog("general")
        with patch.object(general.ai_preferences, "ensure_loaded", new_callable=AsyncMock), \
             patch.object(general.ai_preferences, "get_model", return_value=None), \
             patch.object(general.dsh_gateway, "default_model", return_value="combo:ago-free"), \
             patch.object(general.logfare, "fetch_free_chat_models", new_callable=AsyncMock,
                          return_value=[{"id": "logfare/auto"}]), \
             patch.object(general.dsh_gateway, "fetch_combo_models", new_callable=AsyncMock,
                          return_value=[{"id": "combo:ago-free", "name": "AGO free"}]):
            view = await general.AIDefaultView.create(123)
        self.assertEqual(view.select.model_ids, {"logfare/auto", "combo:ago-free"})
        self.assertTrue(any(option.default and option.value == "combo:ago-free"
                            for option in view.select.options))
