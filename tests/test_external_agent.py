import asyncio
from contextlib import asynccontextmanager
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sales = load_module("whisker_sales", "agents/hosted/sales.py")
with patch.dict("sys.modules", {"sales": sales}):
    agent = load_module("external_agent", "agents/container-app/main.py")
smoke = load_module("external_smoke", "scripts/test-external-agent.py")
deploy = load_module("external_deploy", "scripts/deploy-external-agent.py")


def function_call(name, arguments):
    call = Mock(type="function_call", arguments=json.dumps(arguments), call_id=name)
    call.name = name
    call.model_dump.return_value = {"type": "function_call", "name": name,
                                    "arguments": call.arguments, "call_id": name}
    return call


def response(output, text=""):
    return SimpleNamespace(status="completed", output=output, output_text=text, id="resp-test", usage=None)


class TelemetryValidationTests(unittest.TestCase):
    def complete_trace(self):
        spans = [
            {"operation": "invoke_agent", "tool": ""},
            {"operation": "chat", "tool": ""},
            {"operation": "execute_tool", "tool": "sales_summary"},
            {"operation": "execute_tool", "tool": "check_stock"},
        ]
        return [
            {"agent": "kernel-panic-aca", "success": "True", "itemType": "dependency", **span}
            for span in spans
        ] + [
            {"itemType": "request", "success": True, "name": "POST /chat"},
            {"itemType": "request", "success": "True", "api_type": "mcp-backend"},
            {"itemType": "request", "success": "True", "api": "whisker-works-api"},
        ]

    def test_query_keeps_untagged_gateway_items_and_exceptions(self):
        query = smoke.telemetry_query("a" * 32)
        self.assertIn("union dependencies, requests, exceptions", query)
        self.assertIn("where operation_Id == '" + "a" * 32 + "'", query)
        self.assertNotIn("| where tostring(customDimensions", query)
        self.assertIn("resultCode", query)

    def test_complete_successful_trace_passes(self):
        self.assertTrue(smoke.validate_telemetry(self.complete_trace()))

    def test_missing_agent_or_gateway_telemetry_is_not_a_pass(self):
        self.assertFalse(smoke.validate_telemetry([]))
        rows = self.complete_trace()
        for index in range(len(rows)):
            with self.subTest(missing=index):
                self.assertFalse(smoke.validate_telemetry(rows[:index] + rows[index + 1:]))

    def test_untagged_failed_dependencies_are_not_hidden(self):
        for status in (False, "False", "false"):
            with self.subTest(success=status):
                rows = self.complete_trace() + [
                    {"itemType": "dependency", "name": "forward-request",
                     "success": status, "resultCode": ""},
                ]
                with self.assertRaisesRegex(RuntimeError, "forward-request"):
                    smoke.validate_telemetry(rows)

    def test_exceptions_fail_even_when_all_spans_succeeded(self):
        rows = self.complete_trace() + [
            {"itemType": "exception", "outerMessage": "Client connection was unexpectedly closed."},
        ]
        with self.assertRaisesRegex(RuntimeError, "Client connection"):
            smoke.validate_telemetry(rows)

    def test_real_http_and_agent_failures_are_not_ignored(self):
        for row in (
            {"itemType": "request", "name": "POST /chat", "success": "False", "resultCode": "502"},
            {"itemType": "dependency", "agent": "kernel-panic-aca", "success": False},
        ):
            with self.subTest(row=row):
                with self.assertRaisesRegex(RuntimeError, "failed telemetry"):
                    smoke.validate_telemetry(self.complete_trace() + [row])


class ExternalAgentTests(unittest.TestCase):
    def test_shared_sales_preserve_hosted_behavior(self):
        summary = sales.summarize_sales("category", "2026-09")
        self.assertIn("food: units=1270, revenue=$13,977.30, returns=0", summary.lower())
        self.assertEqual(sales.summarize_sales("unknown"), sales.summarize_sales("category"))
        self.assertEqual(sales.summarize_sales(month="2025-01"), "No sales data for that filter.")

    def test_read_only_surface_and_input_validation(self):
        self.assertEqual({tool["name"] for tool in agent.TOOLS}, {"sales_summary", "check_stock"})
        with self.assertRaisesRegex(ValueError, "not allowed"):
            agent.execute_tool("create_purchase_order", "{}")
        for arguments in ('{"product_id":"WW-004","quantity":20}', '{"product_id":"not-a-product"}'):
            with self.assertRaises(ValueError):
                agent.StockArguments.model_validate_json(arguments)
        client = TestClient(agent.app)
        for body in ({"prompt": ""}, {"prompt": "hello", "mode": "write"}, {"prompt": "x" * 2001}):
            self.assertEqual(client.post("/chat", json=body).status_code, 422)

    def test_model_loop_executes_real_functions_and_reports_evidence(self):
        client = Mock()
        client.responses.create.side_effect = [
            response([function_call("sales_summary", {"group_by": "category", "month": "2026-09"}),
                      function_call("check_stock", {"product_id": "WW-004"})]),
            response([], "Food led September sales. WW-004 is out of stock."),
        ]
        stock = {"mcp_tool": "checkStockLevel",
                 "inventory": {"productId": "WW-004", "stock": 0, "status": "out_of_stock"}}
        with patch.object(agent, "check_stock", new=AsyncMock(return_value=stock)) as check:
            result = agent.run_agent(client, smoke.PROMPT, "gpt-4.1-mini")
        check.assert_awaited_once_with("WW-004")
        self.assertEqual(client.responses.create.call_count, 2)
        self.assertEqual(len(result["tool_calls"]), 2)
        smoke.validate_result({"agent": "kernel-panic-aca", "trace_id": "a" * 32, **result})
        submitted = client.responses.create.call_args.kwargs
        self.assertFalse(submitted["store"])
        self.assertEqual(sum(item.get("type") == "function_call_output" for item in submitted["input"]), 2)

    def test_text_without_tool_execution_is_not_proof(self):
        with self.assertRaisesRegex(RuntimeError, "actual sales_summary"):
            smoke.validate_result({"agent": "kernel-panic-aca", "answer": "Stock is zero", "trace_id": "a" * 32})
        client = Mock()
        client.responses.create.return_value = response([function_call("sales_summary", {})])
        with self.assertRaisesRegex(RuntimeError, "four-round"):
            agent.run_agent(client, "sales", "gpt-4.1-mini")
        self.assertEqual(client.responses.create.call_count, 4)

    def test_agent_surfaces_model_and_tool_failures(self):
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(
            id="resp-incomplete", status="incomplete", output=[], usage=None,
        )
        with self.assertRaisesRegex(RuntimeError, "did not complete"):
            agent.run_agent(client, "sales", "gpt-4.1-mini")
        client.responses.create.return_value = response([
            function_call("check_stock", {"product_id": "WW-004"}),
        ])
        with patch.object(agent, "check_stock", new=AsyncMock(side_effect=RuntimeError("MCP failed"))):
            with self.assertRaisesRegex(RuntimeError, "MCP failed"):
                agent.run_agent(client, "stock", "gpt-4.1-mini")

    def test_mcp_checks_inventory_and_uses_agent_header(self):
        session = AsyncMock()
        session.list_tools.return_value = SimpleNamespace(tools=[SimpleNamespace(name="checkStockLevel")])
        inventory = {"productId": "WW-004", "stock": 0, "status": "out_of_stock"}
        session.call_tool.return_value = SimpleNamespace(isError=False, structuredContent=inventory, content=[])

        @asynccontextmanager
        async def transport(url, headers):
            self.assertEqual(url, "https://whisker.example/whisker-mcp/mcp")
            self.assertEqual(headers["x-agent-id"], "kernel-panic-aca")
            yield None, None, None

        context = AsyncMock()
        context.__aenter__.return_value = session
        with patch.dict("os.environ", {"APIM_GATEWAY_URL": "https://whisker.example",
                                       "APIM_SUBSCRIPTION_KEY": "test-key"}), \
             patch.object(agent, "streamablehttp_client", transport), \
             patch.object(agent, "ClientSession", return_value=context):
            self.assertEqual(asyncio.run(agent.check_stock("WW-004"))["inventory"], inventory)
            session.call_tool.assert_awaited_once_with("checkStockLevel", {"productId": "WW-004"})
            session.call_tool.return_value.isError = True
            with self.assertRaisesRegex(RuntimeError, "returned an error"):
                asyncio.run(agent.check_stock("WW-004"))

    def test_registration_is_idempotent_and_does_not_replace_hosted_agent(self):
        project = Mock()
        definition = project.agents.get.return_value.versions.latest.definition
        definition.kind = "external"
        definition.otel_agent_id = "kernel-panic-aca"
        with patch("builtins.print"):
            deploy.register(project)
        project.agents.create_version.assert_not_called()
        definition.kind = "hosted"
        with self.assertRaisesRegex(RuntimeError, "refusing to overwrite"):
            deploy.register(project)

    def test_deployment_waits_for_authentication_and_never_accepts_public_access(self):
        context = MagicMock()
        client = context.__enter__.return_value
        client.get.side_effect = [Mock(status_code=503), Mock(status_code=401)]
        with patch.object(deploy.httpx, "Client", return_value=context), \
             patch.object(deploy.time, "sleep"), patch("builtins.print"):
            deploy.wait_for_health("https://whisker.example", 401)
        self.assertEqual(client.get.call_count, 2)
        client.get.side_effect = [Mock(status_code=200)]
        with patch.object(deploy.httpx, "Client", return_value=context):
            with self.assertRaisesRegex(RuntimeError, "HTTP 200"):
                deploy.wait_for_health("https://whisker.example", 401)

    def test_apim_policy_has_local_controls_and_managed_identity(self):
        policy = ET.parse(ROOT / "apim/policies/external-agent-policy.xml")
        self.assertEqual(policy.find(".//authentication-managed-identity").get("resource"), "__BACKEND_AUDIENCE__")
        self.assertEqual(policy.find(".//set-status").get("code"), "403")
        self.assertEqual(policy.find(".//rate-limit-by-key").get("calls"), "10")
        self.assertNotIn("context.Response.Body", ET.tostring(policy.getroot(), encoding="unicode"))
        infrastructure = (ROOT / "infra/external-agent.bicep").read_text()
        self.assertIn("allowedApplications: [apimClientId]", infrastructure)
        self.assertIn("allowedPrincipals: { identities: [apimPrincipalId] }", infrastructure)

    def test_optional_cells_are_gated_and_do_not_deploy(self):
        notebook = json.loads((ROOT / "docs/whisker-works-demo-runbook.ipynb").read_text())
        cell = next(cell for cell in notebook["cells"] if cell["id"] == "external-agent-verify")
        source = "".join(cell["source"])
        self.assertIn('"scripts/test-external-agent.py"', source)
        self.assertIn('"--verify-telemetry"', source)
        self.assertIn('approval=""', source)
        self.assertNotIn("--deploy", source)


if __name__ == "__main__":
    unittest.main()
