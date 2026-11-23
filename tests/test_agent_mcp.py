import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("agent_mcp", ROOT / "scripts/test-agent-mcp.py")
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


def response(output, *, status="completed"):
    return {"id": "resp-test", "status": status, "output": output}


def call(name="checkInventory", output=None, **extra):
    return {
        "type": "mcp_call", "name": name, "status": "completed", "error": None,
        "output": json.dumps({"productId": "WW-001", "stock": 42, "status": "in_stock"})
        if output is None else output, **extra,
    }


class AgentMcpTests(unittest.TestCase):
    def test_requires_real_successful_call_not_assistant_text(self):
        for output in ([], [{"type": "message", "content": "checkInventory succeeded"}],
                       [{"type": "mcp_list_tools", "tools": []}]):
            with self.subTest(output=output), self.assertRaisesRegex(smoke.CheckFailed, "No actual MCP"):
                smoke.check_response(response(output), "inventory", ("checkInventory",))
        self.assertEqual(
            smoke.check_response(response([call()]), "inventory", ("checkInventory",)), ["checkInventory"]
        )

    def test_rejects_failures_approval_and_unexpected_tools(self):
        outputs = [
            [call(status="failed")], [call(error={"code": 429})],
            [call(output='{"isError":true,"content":[{"type":"text","text":"failure"}]}')],
            [call(output="")], [{"type": "mcp_approval_request"}],
            [call(name="placeOrder")],
        ]
        for output in outputs:
            with self.subTest(output=output), self.assertRaises(smoke.CheckFailed):
                smoke.check_response(response(output), "inventory", ("checkInventory",))
        with self.assertRaises(smoke.CheckFailed):
            smoke.check_response(response([call()], status="incomplete"), "inventory", ("checkInventory",))

    def test_validates_live_result_shapes_not_exact_stock_counts(self):
        payloads = {
            "catalog": [{"id": "WW-001"}],
            "product": {"id": "WW-001", "name": "Box", "price": 4.99},
            "inventory": {"productId": "WW-001", "stock": 0, "status": "out_of_stock"},
            "order": {"orderId": "ORD-1002", "status": "processing"},
            "fact": {"fact": "Cats purr."},
            "learn-search": "https://learn.microsoft.com/azure/api-management/llm-token-limit-policy",
            "learn-fetch": "# llm-token-limit policy\nLimits tokens per minute.",
            "learn-code": "Python sample: BlobServiceClient(...)",
        }
        for case, payload in payloads.items():
            with self.subTest(case=case):
                smoke.check_payload(case, payload)
                with self.assertRaises(smoke.CheckFailed):
                    smoke.check_payload(case, None)
        for payload in (
            {"productId": "WW-001", "stock": -1, "status": "in_stock"},
            {"productId": "WW-001", "stock": True, "status": "in_stock"},
            {"productId": "WW-002", "stock": 2, "status": "in_stock"},
        ):
            with self.assertRaises(smoke.CheckFailed):
                smoke.check_payload("inventory", payload)

    def test_accepts_standard_mcp_text_envelope(self):
        payload = {"content": [{"type": "text", "text": '{"fact":"Cats purr."}'}], "isError": False}
        self.assertEqual(smoke.decode_output(json.dumps(payload)), {"fact": "Cats purr."})

    def test_fetch_checks_source_arguments_not_a_link_inside_page_text(self):
        item = call(name="microsoft_docs_fetch", output="# llm-token-limit\nControls token usage.",
                    arguments=json.dumps({
                        "url": "https://learn.microsoft.com/azure/api-management/llm-token-limit-policy",
                    }))
        self.assertEqual(
            smoke.check_response(response([item]), "learn-fetch", ("microsoft_docs_fetch",)),
            ["microsoft_docs_fetch"],
        )
        for arguments in (
            "not JSON", '[]', '{}',
            '{"url":"https://untrusted.test/llm-token-limit-policy"}',
            '{"url":"https://learn.microsoft.com/azure/unrelated"}',
        ):
            with self.subTest(arguments=arguments), self.assertRaises(smoke.CheckFailed):
                smoke.check_response(
                    response([{**item, "arguments": arguments}]), "learn-fetch", ("microsoft_docs_fetch",),
                )

    def test_invocation_is_pinned_bounded_and_read_only(self):
        client = Mock()
        client.responses.create.return_value.model_dump.return_value = {"id": "resp-test"}
        with patch.object(smoke.time, "monotonic", return_value=100):
            smoke.invoke(client, "whiskers-concierge", "4", "Check WW-001", deadline=130)
        kwargs = client.responses.create.call_args.kwargs
        self.assertEqual(kwargs["timeout"], 30)
        self.assertEqual(kwargs["extra_body"]["agent_reference"]["version"], "4")
        self.assertIn("Never place or modify an order", kwargs["input"])
        self.assertNotIn("mcp_approval_response", str(kwargs))
        with patch.object(smoke.time, "monotonic", return_value=140):
            with self.assertRaisesRegex(smoke.CheckFailed, "budget"):
                smoke.invoke(client, "agent", None, "test", deadline=130)

    def test_order_discovery_never_executes_tools_and_supports_sse(self):
        methods = []

        def handle(request):
            body = json.loads(request.content)
            methods.append(body["method"])
            if body["method"] == "initialize":
                return httpx.Response(200, json={
                    "jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18"},
                }, headers={"mcp-session-id": "session-test"})
            self.assertEqual(request.headers["mcp-session-id"], "session-test")
            if body["method"] == "notifications/initialized":
                return httpx.Response(202)
            self.assertEqual(body["method"], "tools/list")
            message = {"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "placeAnOrder"}]}}
            return httpx.Response(200, text="event: message\ndata: " + json.dumps(message) + "\n\n",
                                  headers={"content-type": "text/event-stream"})

        client = httpx.Client(transport=httpx.MockTransport(handle))
        with patch.object(smoke.httpx, "Client", return_value=client):
            self.assertEqual(smoke.discover_orders("https://gateway.test", "test-key"), ["placeAnOrder"])
        self.assertEqual(methods, ["initialize", "notifications/initialized", "tools/list"])

    def test_read_only_case_definitions_exclude_order_writes(self):
        for _, names, prompt in (*smoke.STORE_CASES, *smoke.LEARN_CASES):
            self.assertNotIn("placeOrder", names)
            self.assertNotIn("placeAnOrder", names)
            self.assertNotIn("place an order", prompt.lower())


if __name__ == "__main__":
    unittest.main()
