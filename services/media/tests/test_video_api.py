import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI, HTTPException

from app.api import ConfigBody, GenerateBody, ProbeBody, generate_for, probe_models, router, update_config
from app.config import settings
from app.security import Actor, decrypt_secret, encrypt_secret


class VideoApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.actor = Actor(uuid.uuid4(), "user")
        self.config = SimpleNamespace(id=uuid.uuid4(), owner_id=self.actor.id, base_url="https://api.x.ai/v1", model="grok-imagine-video", provider="auto", api_key_encrypted=encrypt_secret("saved-secret"), created_at=None)
        self.session = SimpleNamespace(get=AsyncMock(return_value=self.config), commit=AsyncMock(), refresh=AsyncMock(), add=lambda item: None)

    async def test_saved_key_reused_for_same_endpoint(self):
        body = ProbeBody(base_url=self.config.base_url, config_id=self.config.id)
        with patch("app.api.probe_video_models", new_callable=AsyncMock, return_value={"models": []}) as probe:
            await probe_models(body, self.actor, self.session)
        probe.assert_awaited_once_with(self.config.base_url, "saved-secret", "auto")

    async def test_saved_key_cannot_be_probed_at_another_endpoint(self):
        body = ProbeBody(base_url="https://different.example/v1", config_id=self.config.id)
        with patch("app.api.probe_video_models", new_callable=AsyncMock) as probe:
            with self.assertRaises(HTTPException):
                await probe_models(body, self.actor, self.session)
        probe.assert_not_awaited()

    async def test_other_users_saved_key_is_not_accessible(self):
        self.config.owner_id = uuid.uuid4()
        with self.assertRaises(HTTPException) as raised:
            await probe_models(ProbeBody(base_url=self.config.base_url, config_id=self.config.id), self.actor, self.session)
        self.assertEqual(raised.exception.status_code, 404)

    async def test_update_preserves_encrypted_key_and_provider(self):
        await update_config(self.config.id, ConfigBody(base_url=self.config.base_url, model="grok-imagine-video-1.5"), self.actor, self.session)
        self.assertEqual(decrypt_secret(self.config.api_key_encrypted), "saved-secret")
        self.assertEqual(self.config.provider, "auto")

    async def test_changing_endpoint_requires_new_key(self):
        with self.assertRaises(HTTPException):
            await update_config(self.config.id, ConfigBody(base_url="https://different.example/v1", model="grok-imagine-video"), self.actor, self.session)
        self.session.commit.assert_not_awaited()

    async def test_workflow_generation_uses_saved_provider(self):
        self.config.provider = "xai"
        body = GenerateBody(prompt="雨夜", run_id=uuid.uuid4())
        post = SimpleNamespace()
        with patch("app.api.latest_config", new_callable=AsyncMock, return_value=self.config), patch("app.api.generate_video", new_callable=AsyncMock, return_value=b"video") as generate, patch("app.api.store_video", new_callable=AsyncMock, return_value=post):
            await generate_for(self.actor.id, body, self.session)
        generate.assert_awaited_once_with(self.config.base_url, "saved-secret", "雨夜", self.config.model, "xai")

    async def test_http_provider_contract_requires_actor_and_exposes_protocols(self):
        app = FastAPI()
        app.include_router(router)
        headers = {"x-internal-token": settings.internal_token, "x-user-id": str(self.actor.id)}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            self.assertEqual((await client.get("/api/media/providers")).status_code, 401)
            response = await client.get("/api/media/providers", headers=headers)
            self.assertEqual(response.status_code, 200)
            kinds = {provider["id"] for provider in response.json()}
            self.assertTrue({"ark", "xai", "tencent", "compatible_json"}.issubset(kinds))
            mock = await client.post("/api/media/configs/probe", headers=headers, json={"base_url": "mock"})
            self.assertEqual(mock.status_code, 200)
            self.assertEqual(mock.json()["models"][0]["id"], "mock")
            invalid = await client.post("/api/media/configs/probe", headers=headers, json={"base_url": "mock", "provider": "unsupported"})
            self.assertEqual(invalid.status_code, 422)


if __name__ == "__main__":
    unittest.main()
