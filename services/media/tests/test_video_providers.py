import base64
import hashlib
import hmac
import json
import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException

from app.video_providers import auth_headers, generate_video, make_task, parse_response, probe_video_models, tencent_request

VIDEO = b"\x00\x00\x00\x18ftypmp42fake-test-video"
CDN = "https://cdn.example/video.mp4"


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.host_guard = patch("app.video_providers.assert_download_host")
        self.guard = self.host_guard.start()
        self.interval = patch("app.video_providers.settings.video_poll_interval_seconds", 0)
        self.interval.start()

    async def asyncTearDown(self):
        self.host_guard.stop()
        self.interval.stop()

    async def exercise(self, provider, model, created, completed, expected_path, verify_body=None):
        requests = []
        def respond(request):
            requests.append(request)
            if request.url.host == "cdn.example":
                self.assertNotIn("authorization", request.headers)
                self.assertNotIn("api-key", request.headers)
                return httpx.Response(200, content=VIDEO, headers={"content-type": "video/mp4"})
            if request.method == "POST" and len(requests) == 1:
                self.assertEqual(request.url.path, expected_path)
                if verify_body:
                    verify_body(json.loads(request.content))
                return httpx.Response(200, json=created)
            return httpx.Response(200, json=completed)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            data = await generate_video("https://provider.example", "test-secret", "雨夜", model, provider, client=client)
        self.assertEqual(data, VIDEO)
        self.assertEqual(len(requests), 3)
        return requests

    async def test_xai_async_generation(self):
        requests = await self.exercise("xai", "grok-imagine-video", {"request_id": "job"}, {"status": "done", "video": {"url": CDN}}, "/v1/videos/generations")
        self.assertEqual(requests[1].url.path, "/v1/videos/job")

    async def test_seedance_content_payload(self):
        requests = await self.exercise("ark", "ep-private", {"id": "job"}, {"status": "succeeded", "content": {"video_url": CDN}}, "/api/v3/contents/generations/tasks", lambda body: self.assertEqual(body["content"], [{"type": "text", "text": "雨夜"}]))
        self.assertEqual(requests[1].url.path, "/api/v3/contents/generations/tasks/job")

    async def test_wan_new_generation_and_legacy_dimensions(self):
        requests = await self.exercise("dashscope", "wan2.7-t2v-2026-06-12", {"output": {"task_id": "job", "task_status": "PENDING"}}, {"output": {"task_status": "SUCCEEDED", "video_url": CDN}}, "/api/v1/services/aigc/video-generation/video-synthesis", lambda body: self.assertEqual(body["parameters"]["resolution"], "720P"))
        self.assertEqual(requests[0].headers["X-DashScope-Async"], "enable")
        self.assertEqual(make_task("https://p.example", "dashscope", "wan2.6-t2v", "x").body["parameters"]["size"], "1280*720")

    async def test_minimax_h3_v2(self):
        await self.exercise("minimax", "MiniMax-H3", {"task_id": "job"}, {"task": {"id": "job", "status": "succeeded", "content": {"url": CDN}}}, "/v2/video_generation")

    async def test_minimax_hailuo_requires_file_retrieval(self):
        paths = []
        def respond(request):
            paths.append(request.url.path)
            if request.url.path == "/v1/video_generation":
                return httpx.Response(200, json={"task_id": "job", "base_resp": {"status_code": 0}})
            if request.url.path == "/v1/query/video_generation":
                self.assertEqual(request.url.params["task_id"], "job")
                return httpx.Response(200, json={"status": "Success", "file_id": "file"})
            if request.url.path == "/v1/files/retrieve":
                return httpx.Response(200, json={"file": {"download_url": CDN}})
            return httpx.Response(200, content=VIDEO, headers={"content-type": "video/mp4"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            self.assertEqual(await generate_video("https://p.example/v1", "secret", "x", "MiniMax-Hailuo-2.3", "minimax", client=client), VIDEO)
        self.assertEqual(len(paths), 4)

    async def test_kling_nested_video_result(self):
        await self.exercise("kling", "kling-v3", {"code": 0, "data": {"task_id": "job", "task_status": "submitted"}}, {"code": 0, "data": {"task_status": "succeed", "task_result": {"videos": [{"url": CDN}]}}}, "/v1/videos/text2video", lambda body: self.assertEqual(body["model_name"], "kling-v3"))

    async def test_vidu_token_and_creations(self):
        requests = await self.exercise("vidu", "viduq3-pro", {"task_id": "job", "state": "created"}, {"state": "success", "creations": [{"url": CDN}]}, "/ent/v2/text2video")
        self.assertEqual(requests[0].headers["authorization"], "Token test-secret")

    async def test_pixverse_numeric_status_and_api_key(self):
        requests = await self.exercise("pixverse", "v6-max", {"ErrCode": 0, "Resp": {"video_id": 12}}, {"ErrCode": 0, "Resp": {"status": 1, "url": CDN}}, "/openapi/v2/video/text/generate")
        self.assertEqual(requests[0].headers["api-key"], "test-secret")
        self.assertIn("ai-trace-id", requests[0].headers)

    async def test_siliconflow_post_polling(self):
        requests = await self.exercise("siliconflow", "Wan-AI/Wan2.2-T2V-A14B", {"requestId": "job"}, {"status": "Succeed", "results": {"videos": [{"url": CDN}]}}, "/v1/video/submit")
        self.assertEqual(requests[1].method, "POST")
        self.assertEqual(json.loads(requests[1].content), {"requestId": "job"})

    async def test_zhipu_video_result(self):
        await self.exercise("zhipu", "cogvideox-3", {"id": "job", "task_status": "PROCESSING"}, {"task_status": "SUCCESS", "video_result": [{"url": CDN}]}, "/api/paas/v4/videos/generations")

    async def test_tencent_signed_submission_and_query(self):
        requests = []
        def respond(request):
            requests.append(request)
            if request.url.host == "cdn.example":
                self.assertNotIn("authorization", request.headers)
                return httpx.Response(200, content=VIDEO, headers={"content-type": "video/mp4"})
            self.assertTrue(request.headers["authorization"].startswith("TC3-HMAC-SHA256 Credential=access/"))
            self.assertEqual(request.headers["x-tc-version"], "2024-05-23")
            action = request.headers["x-tc-action"]
            if action == "SubmitHunyuanToVideoJob":
                self.assertEqual(json.loads(request.content), {"Prompt": "雨夜", "Resolution": "720p"})
                return httpx.Response(200, json={"Response": {"JobId": "job", "RequestId": "trace"}})
            self.assertEqual(action, "DescribeHunyuanToVideoJob")
            self.assertEqual(json.loads(request.content), {"JobId": "job"})
            return httpx.Response(200, json={"Response": {"Status": "DONE", "ResultVideoUrl": CDN, "ErrorCode": ""}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            self.assertEqual(await generate_video("https://vclm.tencentcloudapi.com", "access:secret", "雨夜", "hunyuan-video", "tencent", client=client), VIDEO)
        self.assertEqual(len(requests), 3)

    async def test_json_compatible_submission(self):
        def respond(request):
            if request.method == "POST":
                self.assertEqual(json.loads(request.content), {"model": "grok-imagine-video", "prompt": "x"})
                return httpx.Response(200, json={"video_url": CDN})
            return httpx.Response(200, content=VIDEO, headers={"content-type": "video/mp4"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            self.assertEqual(await generate_video("https://relay.example/v1", "secret", "x", "grok-imagine-video", "compatible_json", client=client), VIDEO)

    async def test_compatible_multipart_and_content_download(self):
        requests = []
        def respond(request):
            requests.append(request)
            if request.method == "POST":
                self.assertIn("multipart/form-data", request.headers["content-type"])
                self.assertIn(b'name="model"', request.content)
                return httpx.Response(200, json={"id": "job", "status": "queued"})
            if request.url.path.endswith("/content"):
                self.assertEqual(request.headers["authorization"], "Bearer secret")
                return httpx.Response(200, content=VIDEO, headers={"content-type": "video/mp4"})
            return httpx.Response(200, json={"id": "job", "status": "completed"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            data = await generate_video("https://relay.example/v1/models", "secret", "雨夜", "sora-2", client=client)
        self.assertEqual(data, VIDEO)
        self.assertEqual(len(requests), 3)

    async def test_custom_sync_and_redirect_do_not_forward_secrets(self):
        def respond(request):
            if request.url.path == "/generate":
                self.assertEqual(json.loads(request.content), {"prompt": "x"})
                return httpx.Response(200, json={"video_url": "https://cdn.example/redirect"})
            self.assertNotIn("authorization", request.headers)
            if request.url.path == "/redirect":
                return httpx.Response(302, headers={"location": CDN})
            return httpx.Response(200, content=VIDEO, headers={"content-type": "application/octet-stream"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            self.assertEqual(await generate_video("https://p.example/generate", "secret", "x", provider="custom", client=client), VIDEO)
        self.assertEqual(self.guard.call_count, 2)

    async def test_empty_compatible_content_is_rejected(self):
        def respond(request):
            if request.method == "POST":
                return httpx.Response(200, json={"id": "job", "status": "queued"})
            if request.url.path.endswith("/content"):
                return httpx.Response(200, content=b"", headers={"content-type": "video/mp4"})
            return httpx.Response(200, json={"id": "job", "status": "completed"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with self.assertRaises(HTTPException):
                await generate_video("https://relay.example/v1", "secret", "x", "sora-2", client=client)

    async def test_failed_job_is_not_downloaded(self):
        def respond(request):
            return httpx.Response(200, json={"request_id": "job", "status": "failed", "error": {"message": "test-secret rejected"}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with self.assertRaises(HTTPException) as raised:
                await generate_video("https://p.example", "test-secret", "x", "grok-imagine-video", "xai", client=client)
        self.assertNotIn("test-secret", raised.exception.detail)
        self.guard.assert_not_called()

    async def test_poll_timeout_keeps_task_id(self):
        def respond(request):
            return httpx.Response(200, json={"request_id": "job", "status": "pending"})
        with patch("app.video_providers.settings.video_timeout_seconds", 0):
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                with self.assertRaises(HTTPException) as raised:
                    await generate_video("https://p.example", "secret", "x", "grok-imagine-video", "xai", client=client)
        self.assertEqual(raised.exception.status_code, 504)
        self.assertIn("job", raised.exception.detail)

    async def test_native_presets_are_explicitly_not_permission_checks(self):
        result = await probe_video_models("https://api.vidu.cn/ent/v2", "secret", "vidu")
        self.assertEqual(result["source"], "preset")
        self.assertIn("未验证", result["hint"])

    async def test_probe_filters_models_and_auth_failures_do_not_fallback(self):
        def respond(request):
            self.assertEqual(request.url.path, "/v1/models")
            return httpx.Response(200, json={"data": [{"id": "gpt-4o"}, {"id": "grok-imagine-video"}]})
        client_factory = httpx.AsyncClient
        with patch("app.video_providers.httpx.AsyncClient", lambda **kwargs: client_factory(transport=httpx.MockTransport(respond), **kwargs)):
            result = await probe_video_models("https://relay.example/v1/videos", "secret")
        self.assertEqual(result["filtered_count"], 1)
        self.assertEqual([model["id"] for model in result["models"]], ["grok-imagine-video"])
        def denied(request):
            return httpx.Response(401, json={"error": {"message": "Invalid key"}})
        with patch("app.video_providers.httpx.AsyncClient", lambda **kwargs: client_factory(transport=httpx.MockTransport(denied), **kwargs)):
            with self.assertRaises(HTTPException):
                await probe_video_models("https://api.x.ai/v1", "secret")

    async def test_native_chat_only_list_falls_back_to_labelled_video_presets(self):
        def respond(request):
            return httpx.Response(200, json={"data": [{"id": "grok-4"}]})
        client_factory = httpx.AsyncClient
        with patch("app.video_providers.httpx.AsyncClient", lambda **kwargs: client_factory(transport=httpx.MockTransport(respond), **kwargs)):
            result = await probe_video_models("https://api.x.ai/v1", "secret")
        self.assertEqual(result["source"], "preset")
        self.assertEqual(result["filtered_count"], 1)
        self.assertTrue(all("video" in model["id"] for model in result["models"]))


class KlingSigningTests(unittest.TestCase):
    def test_access_key_secret_key_are_signed(self):
        token = auth_headers("kling", "access:secret")["Authorization"].removeprefix("Bearer ")
        header, body, signature = token.split(".")
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        self.assertEqual(claims["iss"], "access")
        expected = base64.urlsafe_b64encode(hmac.new(b"secret", f"{header}.{body}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
        self.assertEqual(signature, expected)

    def test_http_200_business_errors_are_rejected(self):
        for payload in ({"base_resp": {"status_code": 1004, "status_msg": "denied"}}, {"ErrCode": 400, "ErrMsg": "denied"}, {"code": 1001, "message": "denied"}):
            with self.subTest(payload=payload), self.assertRaises(HTTPException):
                parse_response(httpx.Response(200, json=payload), "secret")

    def test_tencent_signature_binds_body_and_timestamp(self):
        with patch("app.video_providers.time.time", return_value=1720000000):
            first_body, first = tencent_request("https://vclm.tencentcloudapi.com", "access:secret", {"Prompt": "a"}, "SubmitHunyuanToVideoJob")
            _, changed = tencent_request("https://vclm.tencentcloudapi.com", "access:secret", {"Prompt": "b"}, "SubmitHunyuanToVideoJob")
            _, repeated = tencent_request("https://vclm.tencentcloudapi.com", "access:secret", {"Prompt": "a"}, "SubmitHunyuanToVideoJob")
        self.assertEqual(json.loads(first_body), {"Prompt": "a"})
        self.assertEqual(first["X-TC-Timestamp"], "1720000000")
        self.assertEqual(first["Authorization"], repeated["Authorization"])
        self.assertNotEqual(first["Authorization"], changed["Authorization"])
        self.assertNotIn("secret", first["Authorization"])
        with self.assertRaises(HTTPException):
            tencent_request("https://vclm.tencentcloudapi.com", "invalid", {}, "SubmitHunyuanToVideoJob")

    def test_tencent_http_200_auth_error_is_rejected(self):
        with self.assertRaises(HTTPException):
            parse_response(httpx.Response(200, json={"Response": {"Error": {"Code": "AuthFailure", "Message": "denied"}}}), "access:secret")


if __name__ == "__main__":
    unittest.main()
