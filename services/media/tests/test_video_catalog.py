import unittest

from fastapi import HTTPException

from app.video_catalog import filter_models, is_text_to_video, resolve_provider, validate_model
from app.video_providers import api_root


class VideoCatalogTests(unittest.TestCase):
    def test_mixed_model_list_only_returns_text_to_video(self):
        raw = ["gpt-4o", "grok-4", "grok-imagine-image", "grok-imagine-video", "doubao-seedance-2-0-260128", "wan2.6-t2v", "wan2.6-i2v", "MiniMax-Hailuo-2.3", "MiniMax-Hailuo-2.3-Fast", "kling-v2-6", "viduq3-pro", "viduq3-pro-fast", "Qwen/Qwen2.5-VL", "black-forest-labs/FLUX.1", "cogvideox-3"]
        found, removed = filter_models({"data": [{"id": mid} for mid in raw]}, "compatible")
        expected = {"grok-imagine-video", "doubao-seedance-2-0-260128", "wan2.6-t2v", "MiniMax-Hailuo-2.3", "kling-v2-6", "viduq3-pro", "cogvideox-3"}
        self.assertEqual({item["id"] for item in found}, expected)
        self.assertEqual(removed, len(raw) - len(expected))

    def test_explicit_modalities_override_name(self):
        self.assertFalse(is_text_to_video({"id": "seedance-x", "output_modalities": ["text"]}))
        self.assertFalse(is_text_to_video({"id": "new-video", "input_modalities": ["image"], "output_modalities": ["video"]}))
        self.assertTrue(is_text_to_video({"id": "unfamiliar-model", "architecture": {"input_modalities": ["text"], "output_modalities": ["video"]}}))
        self.assertTrue(is_text_to_video({"id": "private-model", "capabilities": {"text_to_video": True}}))
        self.assertFalse(is_text_to_video({"id": "wan2.6-t2v", "capabilities": {"text_to_video": False}}))

    def test_deduplicates_and_rejects_malformed_catalog(self):
        found, _ = filter_models(["grok-imagine-video", {"id": "grok-imagine-video"}, None, 42], "xai")
        self.assertEqual(len(found), 1)
        with self.assertRaises(HTTPException):
            filter_models({"data": "not-an-array"}, "compatible")

    def test_protocol_follows_endpoint_not_model(self):
        self.assertEqual(resolve_provider("https://api.x.ai/v1"), "xai")
        self.assertEqual(resolve_provider("https://ark.cn-beijing.volces.com/api/v3"), "ark")
        self.assertEqual(resolve_provider("https://relay.example/v1"), "compatible")
        self.assertEqual(resolve_provider("https://relay.example/v1", "ark"), "ark")
        self.assertEqual(resolve_provider("https://api.x.ai.evil.example/v1"), "compatible")
        self.assertEqual(resolve_provider("https://custom.example/generate"), "custom")

    def test_normalizes_roots_and_full_endpoints(self):
        cases = [
            ("https://relay.example/v1/models", "compatible", "https://relay.example/v1"),
            ("https://relay.example/v1/videos", "compatible", "https://relay.example/v1"),
            ("https://ark.example/api/v3/contents/generations/tasks", "ark", "https://ark.example/api/v3"),
            ("https://api.x.ai", "xai", "https://api.x.ai/v1"),
            ("https://workspace.example/prefix/api/v1", "dashscope", "https://workspace.example/prefix/api/v1"),
        ]
        for url, kind, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(api_root(url, kind), expected)

    def test_invalid_addresses_and_retired_official_api_are_rejected(self):
        for url in ("file:///tmp/video", "https://secret@example.com", "https://example.com?key=secret", "https://api.openai.com/v1"):
            with self.subTest(url=url), self.assertRaises(HTTPException):
                resolve_provider(url)
        with self.assertRaises(HTTPException):
            resolve_provider("https://api.openai.com/v1", "compatible")

    def test_manual_resource_ids_allowed_but_known_nonvideo_models_rejected(self):
        validate_model("ep-private-deployment", "ark")
        validate_model("company-private-video-model", "compatible")
        validate_model("", "custom")
        for model in ("", "gpt-4o", "wan2.6-i2v", "deepseek-chat", "grok-4", "grok-imagine-image"):
            with self.subTest(model=model), self.assertRaises(HTTPException):
                validate_model(model, "compatible")


if __name__ == "__main__":
    unittest.main()
