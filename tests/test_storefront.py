import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import httpx
from fastapi.testclient import TestClient
from openai import APIConnectionError, BadRequestError, RateLimitError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/catstore-api"))
SPEC = importlib.util.spec_from_file_location("storefront", ROOT / "src/catstore-api/main.py")
storefront = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(storefront)


def api_error(message, *, code="tool_user_error", status=400, headers=None):
    response = httpx.Response(
        status, request=httpx.Request("POST", "https://foundry.test/responses"), headers=headers,
    )
    cls = RateLimitError if status == 429 else BadRequestError
    return cls(message, response=response, body={"error": {"code": code, "message": message}})


class StorefrontChatTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "FOUNDRY_PROJECT_ENDPOINT": "https://foundry.test",
            "STOREFRONT_AGENT_NAME": "whiskers-concierge-pro",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.project_patch = patch.object(storefront, "AIProjectClient")
        self.project_factory = self.project_patch.start()
        self.addCleanup(self.project_patch.stop)
        self.credential_patch = patch.object(storefront, "DefaultAzureCredential")
        self.credential_factory = self.credential_patch.start()
        self.addCleanup(self.credential_patch.stop)
        self.project = self.project_factory.return_value.__enter__.return_value
        self.upstream = self.project.get_openai_client.return_value.__enter__.return_value
        self.upstream.responses.create.return_value = SimpleNamespace(
            id="resp-whiskers", output_text="Purr-fect! Seven pods are in stock.",
        )
        self.client = TestClient(storefront.app)
        self.addCleanup(self.client.close)

    def test_initial_and_followup_requests_preserve_the_agent_and_history(self):
        for previous in (None, "resp-previous"):
            with self.subTest(previous=previous):
                result = self.client.post("/api/chat", json={
                    "message": "Check WW-005", "previousResponseId": previous,
                })
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json(), {
                    "reply": "Purr-fect! Seven pods are in stock.", "responseId": "resp-whiskers",
                })
                expected = {
                    "input": "Check WW-005",
                    "extra_body": {"agent_reference": {
                        "name": "whiskers-concierge-pro", "type": "agent_reference",
                    }},
                }
                if previous:
                    expected["previous_response_id"] = previous
                self.upstream.responses.create.assert_called_with(**expected)
        self.project_factory.return_value.__exit__.assert_called()
        self.credential_factory.return_value.__exit__.assert_called()

    def test_throttling_returns_actionable_429_without_replaying_tools(self):
        cases = [
            (api_error("Error from remote server: 429. Try again in 17 seconds."), "18"),
            (api_error("Rate limited", status=429, headers={"Retry-After": "9"}), "10"),
        ]
        for error, delay in cases:
            with self.subTest(delay=delay):
                self.upstream.responses.create.reset_mock()
                self.upstream.responses.create.side_effect = error
                with self.assertLogs("storefront", level="WARNING") as logs:
                    result = self.client.post("/api/chat", json={
                        "message": "Place an order", "previousResponseId": "resp-previous",
                    })
                self.assertEqual(result.status_code, 429)
                self.assertEqual(result.headers["Retry-After"], delay)
                self.assertIn(f"wait {delay} seconds", result.json()["detail"])
                self.assertNotIn("BadRequestError", result.json()["detail"])
                self.upstream.responses.create.assert_called_once()
                self.assertNotIn("Place an order", "\n".join(logs.output))

    def test_other_errors_remain_failures_and_do_not_leak_upstream_details(self):
        errors = [
            api_error("Secret upstream detail", code="model_not_found"),
            api_error("Remote server returned 401"),
            APIConnectionError(request=httpx.Request("POST", "https://foundry.test/responses")),
        ]
        for error in errors:
            with self.subTest(error=type(error).__name__):
                self.upstream.responses.create.reset_mock()
                self.upstream.responses.create.side_effect = error
                with self.assertLogs("storefront", level="WARNING"):
                    result = self.client.post("/api/chat", json={"message": "Hello"})
                self.assertEqual(result.status_code, 502)
                self.assertNotIn("Secret", result.text)
                self.upstream.responses.create.assert_called_once()

    def test_missing_configuration_and_invalid_requests_do_not_call_foundry(self):
        with patch.dict(os.environ, {"STOREFRONT_AGENT_NAME": ""}):
            self.assertEqual(self.client.post("/api/chat", json={"message": "Hello"}).status_code, 503)
        for message in ("", "x" * 2001):
            self.assertEqual(self.client.post("/api/chat", json={"message": message}).status_code, 422)
        self.project_factory.assert_not_called()

    def test_unexpected_programming_errors_are_not_disguised_as_gateway_failures(self):
        self.upstream.responses.create.side_effect = RuntimeError("unexpected bug")
        with self.assertRaisesRegex(RuntimeError, "unexpected bug"):
            self.client.post("/api/chat", json={"message": "Hello"})


class McpPolicyTests(unittest.TestCase):
    def test_only_tool_calls_are_limited_and_the_body_is_preserved(self):
        policy = ET.parse(ROOT / "apim/policies/mcp-tools-policy.xml").getroot()
        condition = policy.find("inbound/choose/when")
        self.assertIn('context.Request.Method != "POST"', condition.attrib["condition"])
        self.assertIn('"tools/call"', condition.attrib["condition"])
        self.assertIn("preserveContent: true", condition.attrib["condition"])
        self.assertIn("JsonReaderException", condition.attrib["condition"])
        limit = condition.find("rate-limit-by-key")
        self.assertEqual(limit.attrib["calls"], "30")
        self.assertEqual(limit.attrib["renewal-period"], "60")
        self.assertIn("context.Api.Id", limit.attrib["counter-key"])
        self.assertIn("context.Subscription?.Id", limit.attrib["counter-key"])
        self.assertEqual(limit.attrib["retry-after-header-name"], "Retry-After")
        self.assertIsNone(policy.find("inbound/rate-limit-by-key"))
        self.assertNotIn("context.Response.Body", ET.tostring(policy, encoding="unicode"))

    def test_storefront_deployment_includes_shared_error_classifier(self):
        deploy = (ROOT / "scripts/deploy.sh").read_text()
        self.assertIn("main.py foundry_errors.py requirements.txt data static", deploy)


if __name__ == "__main__":
    unittest.main()
