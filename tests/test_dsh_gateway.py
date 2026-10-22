"""DSH gateway integration contract using a loopback OpenAI-compatible server."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from aiohttp import web

from core import dsh_gateway


class DshGatewayTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []

        async def models(request):
            self.requests.append((request.path, request.headers.get("Authorization")))
            return web.json_response({"data": [
                {"id": "combo:ago-free", "name": "AGO free"},
                {"id": "openrouter/example"},
            ]})

        async def chat(request):
            self.requests.append((request.path, request.headers.get("Authorization"),
                                  await request.json()))
            return web.json_response({"choices": [{"message": {"content": "切替後の回答"}}]})

        app = web.Application()
        app.router.add_get("/v1/models", models)
        app.router.add_post("/v1/chat/completions", chat)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.env = patch.dict(os.environ, {
            "DSH_GATEWAY_BASE_URL": f"http://127.0.0.1:{port}/v1",
            "DSH_GATEWAY_API_KEY": "test-gateway-key",
            "DSH_GATEWAY_MODEL": "combo:ago-free",
        })
        self.env.start()

    async def asyncTearDown(self):
        self.env.stop()
        await self.runner.cleanup()

    async def test_combo_catalog_and_chat_use_gateway_key(self):
        self.assertEqual(dsh_gateway.default_model(), "combo:ago-free")
        self.assertEqual(await dsh_gateway.fetch_combo_models(), [
            {"id": "combo:ago-free", "name": "AGO free"},
        ])
        answer = await dsh_gateway.chat("combo:ago-free", [
            {"role": "user", "content": "こんにちは"},
        ])
        self.assertEqual(answer, "切替後の回答")
        self.assertEqual(self.requests[0], ("/v1/models", "Bearer test-gateway-key"))
        self.assertEqual(self.requests[1][0:2],
                         ("/v1/chat/completions", "Bearer test-gateway-key"))
        self.assertEqual(self.requests[1][2]["model"], "combo:ago-free")

    async def test_non_combo_model_is_rejected(self):
        with self.assertRaises(ValueError):
            await dsh_gateway.chat("openrouter/example", [])
        self.assertEqual(self.requests, [])
