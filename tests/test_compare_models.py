import importlib.util
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx
from openai import BadRequestError, RateLimitError


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("compare_models", ROOT / "agents/procode/compare_models.py")
compare_models = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compare_models)


def api_error(message, *, code="tool_user_error", status=400, headers=None):
    response = httpx.Response(status, request=httpx.Request("POST", "https://foundry.test/responses"),
                              headers=headers)
    cls = RateLimitError if status == 429 else BadRequestError
    return cls(message, response=response,
               body={"error": {"message": message, "code": code}})


MCP_THROTTLE = (
    "Error encountered while fetching tool listOrSearchProducts from remote server: "
    "https://gateway.test/whisker-mcp/mcp. Details: Response status code does not indicate "
    'success: 429 (Too Many Requests). Response body: { "statusCode": 429, '
    '"message": "Rate limit is exceeded. Try again in 1 seconds." }.'
)


class CompareModelsTests(unittest.TestCase):
    def test_wrapped_mcp_429_retries_the_same_version_and_prompt(self):
        client = Mock()
        client.responses.create.side_effect = [
            api_error(MCP_THROTTLE),
            SimpleNamespace(output_text="out of stock", usage=SimpleNamespace(total_tokens=42)),
        ]
        with patch.object(compare_models.time, "sleep") as sleep:
            result = compare_models.run(client, "whiskers-concierge-pro", "3", "Check WW-004")
        sleep.assert_called_once_with(2.0)
        self.assertEqual(client.responses.create.call_args_list[0],
                         client.responses.create.call_args_list[1])
        self.assertEqual(result["answer"], "out of stock")
        self.assertEqual(result["tokens"], 42)
        self.assertEqual(result["retries"], 1)

    def test_server_hints_and_backoff(self):
        cases = [
            (api_error(MCP_THROTTLE.replace("in 1 seconds", "in 60 seconds")), 0, 61),
            (api_error("Too Many Requests", status=429, headers={"Retry-After": "10"}), 0, 11),
            (api_error(MCP_THROTTLE), 2, 8),
            (api_error(MCP_THROTTLE), 8, 30),
        ]
        for error, retry, expected in cases:
            with self.subTest(retry=retry, expected=expected):
                self.assertEqual(compare_models.throttle_retry_delay(error, retry), expected)

    def test_exhaustion_preserves_original_error(self):
        client = Mock()
        error = api_error(MCP_THROTTLE)
        client.responses.create.side_effect = error
        with patch.object(compare_models.time, "sleep") as sleep:
            with self.assertRaises(BadRequestError) as raised:
                compare_models.run(client, "whiskers", "2", "Check stock", max_retries=2)
        self.assertIs(raised.exception, error)
        self.assertEqual(client.responses.create.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2.0, 4.0])

    def test_non_throttling_bad_requests_are_not_retried(self):
        for error in (
            api_error("Remote server returned 401 Unauthorized"),
            api_error("Model does not exist", code="model_not_found"),
            api_error("Prompt contains product 429", code="invalid_prompt"),
        ):
            client = Mock()
            client.responses.create.side_effect = error
            with patch.object(compare_models.time, "sleep") as sleep:
                with self.assertRaises(BadRequestError):
                    compare_models.run(client, "whiskers", "3", "Hello")
            sleep.assert_not_called()
            client.responses.create.assert_called_once()

    def test_retries_can_be_disabled(self):
        client = Mock()
        client.responses.create.side_effect = api_error(MCP_THROTTLE)
        with patch.object(compare_models.time, "sleep") as sleep:
            with self.assertRaises(BadRequestError):
                compare_models.run(client, "whiskers", "3", "Hello", max_retries=0)
        sleep.assert_not_called()
        client.responses.create.assert_called_once()

    def test_success_without_retry_preserves_metrics(self):
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(output_text="Purrfect", usage=None)
        with patch.object(compare_models.time, "perf_counter", side_effect=[10, 12.345]):
            result = compare_models.run(client, "whiskers", "2", "Hello")
        self.assertEqual(result, {"answer": "Purrfect", "latency_s": 2.35, "tokens": None, "retries": 0})

    def test_main_supports_ci_output_and_preserves_default_report_location(self):
        for explicit_output in (False, True):
            with self.subTest(explicit_output=explicit_output), TemporaryDirectory() as directory:
                root = Path(directory)
                dataset = root / "eval.jsonl"
                dataset.write_text(json.dumps({"query": "Stock?", "must_include": ["stock"]}) + "\n")
                output = root / "release/nested/comparison.json"
                arguments = ["compare_models.py", "--agent", "whiskers-release", "--a", "7", "--b", "9",
                             "--dataset", str(dataset)]
                if explicit_output:
                    arguments.extend(["--output", str(output)])
                with patch.object(compare_models, "HERE", root), \
                     patch.object(compare_models, "AIProjectClient"), \
                     patch.object(compare_models, "DefaultAzureCredential"), \
                     patch.object(compare_models, "run", return_value={
                         "answer": "In stock", "latency_s": 1, "tokens": 10, "retries": 0,
                     }) as run, \
                     patch.dict(os.environ, {"FOUNDRY_PROJECT_ENDPOINT": "https://foundry.test"}), \
                     patch.object(sys, "argv", arguments), patch("builtins.print"):
                    compare_models.main()
                if not explicit_output:
                    output, = (root / "results").glob("compare-v7-v9-*.json")
                report = json.loads(output.read_text())
                self.assertEqual(set(report[0]), {"query", "7", "9"})
                self.assertTrue(report[0]["9"]["pass"])
                self.assertEqual([call.args[1:3] for call in run.call_args_list],
                                 [("whiskers-release", "7"), ("whiskers-release", "9")])


if __name__ == "__main__":
    unittest.main()
