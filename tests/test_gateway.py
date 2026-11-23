import contextlib
import importlib.util
import io
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx
import openai


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("test_gateway_script", ROOT / "scripts/test-gateway.py")
gateway = importlib.util.module_from_spec(SPEC)
with patch("dotenv.load_dotenv"), patch.dict(os.environ, {"APIM_GATEWAY_URL": "https://gateway.test"}):
    SPEC.loader.exec_module(gateway)


class GatewayThrottleTests(unittest.TestCase):
    def run_throttle(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"APIM_BRONZE_KEY": "test-key"}), contextlib.redirect_stdout(output):
            gateway.throttle()
        return output.getvalue()

    def test_first_429_is_not_retried_and_usage_is_reported(self):
        requests = []

        def respond(request):
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(200, headers={
                    "x-consumed-tokens": "170", "x-remaining-tokens": "0",
                }, json={
                    "id": "chatcmpl-test", "object": "chat.completion", "created": 0,
                    "model": "gpt-4.1-mini",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "Meow"},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 150, "total_tokens": 170},
                })
            return httpx.Response(429, headers={"Retry-After": "30"}, json={
                "error": {"message": "Token rate limit exceeded", "code": "RateLimitExceeded"},
            })

        with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
            c = openai.AzureOpenAI(
                azure_endpoint="https://gateway.test/models", api_key="test-key",
                api_version="2024-10-21", http_client=http_client,
            )
            with patch.object(gateway, "client", return_value=c):
                output = self.run_throttle()
            self.assertEqual(c.max_retries, 2)
        self.assertEqual(len(requests), 2)
        self.assertIn("200 OK  actual=170  apim-consumed=170  remaining=0", output)
        self.assertIn("429 Too Many Requests  retry-after=30", output)
        self.assertIn("Token rate limit exceeded", output)
        self.assertNotIn("Bronze budget exhausted", output)

    def test_missing_usage_and_headers_are_not_reported_as_zero(self):
        c = Mock()
        c.with_options.return_value = c
        completion = SimpleNamespace(usage=None)
        error = openai.RateLimitError(
            "Throttled",
            response=httpx.Response(429, request=httpx.Request("POST", "https://gateway.test")),
            body=None,
        )
        with patch.object(gateway, "client", return_value=c), patch.object(
            gateway, "ask", side_effect=[(completion, {}), error],
        ):
            output = self.run_throttle()
        c.with_options.assert_called_once_with(max_retries=0)
        self.assertIn("actual=missing  apim-consumed=missing  remaining=missing", output)
        self.assertIn("retry-after=missing", output)

    def test_no_throttling_fails_after_ten_requests(self):
        c = Mock()
        c.with_options.return_value = c
        with patch.object(gateway, "client", return_value=c), patch.object(
            gateway, "ask", return_value=(SimpleNamespace(usage=None), {}),
        ) as ask:
            with self.assertRaisesRegex(RuntimeError, "No 429 observed after 10 requests"):
                self.run_throttle()
        self.assertEqual(ask.call_count, 10)

    def test_other_errors_are_not_mistaken_for_throttling(self):
        error = openai.AuthenticationError(
            "Invalid subscription",
            response=httpx.Response(401, request=httpx.Request("POST", "https://gateway.test")),
            body=None,
        )
        with patch.object(gateway, "client"), patch.object(gateway, "ask", side_effect=error):
            with self.assertRaises(openai.AuthenticationError) as raised:
                self.run_throttle()
        self.assertIs(raised.exception, error)


if __name__ == "__main__":
    unittest.main()
