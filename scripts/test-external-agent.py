"""Verify optional Topic 6: actual tools, gateway controls and Foundry-attributed spans."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import time

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from dotenv import dotenv_values
import httpx

ROOT = Path(__file__).resolve().parents[1]
PROMPT = ("Summarize September 2026 sales by category using sales_summary, then use check_stock "
          "to check current stock of WW-004. Make both actual tool calls. Do not place an order.")


def validate_result(result: dict):
    if result.get("agent") != "kernel-panic-aca" or not result.get("answer"):
        raise RuntimeError("Response is not a successful Kernel Panic ACA answer")
    calls = result.get("tool_calls", [])
    sales = [call for call in calls if call.get("name") == "sales_summary"]
    stock = [call for call in calls if call.get("name") == "check_stock"]
    if not sales or not stock or any(call.get("name") not in ("sales_summary", "check_stock") for call in calls):
        raise RuntimeError("Expected actual sales_summary and check_stock calls, and no other tools")
    if not any(call["arguments"].get("month") == "2026-09"
               and "Food" in call["result"].get("summary", "").title() for call in sales):
        raise RuntimeError("Sales call did not return September category data")
    if not any(call["arguments"].get("product_id") == "WW-004"
               and call["result"].get("mcp_tool") in ("checkStockLevel", "checkInventory")
               and call["result"].get("inventory", {}).get("productId") == "WW-004"
               and type(call["result"]["inventory"].get("stock")) is int
               and call["result"]["inventory"]["stock"] >= 0
               and call["result"]["inventory"].get("status") in ("in_stock", "low_stock", "out_of_stock")
               for call in stock):
        raise RuntimeError("Inventory evidence did not include a real WW-004 MCP result")
    if not re.fullmatch(r"[0-9a-f]{32}", result.get("trace_id", "")) or result["trace_id"] == "0" * 32:
        raise RuntimeError("Response is missing a correlated OpenTelemetry trace ID")


def telemetry_query(trace_id: str) -> str:
    return (
        "union dependencies, requests, exceptions\n"
        "| where timestamp > ago(1h)\n"
        f"| where operation_Id == '{trace_id}'\n"
        "| project id, itemType, name, operation_Id, "
        "agent=tostring(customDimensions['gen_ai.agent.id']), "
        "operation=tostring(customDimensions['gen_ai.operation.name']), "
        "tool=tostring(customDimensions['gen_ai.tool.name']), "
        "api=tostring(customDimensions['API Name']), "
        "api_type=tostring(customDimensions['api.type']), "
        "success, resultCode, outerMessage\n"
    )


def validate_telemetry(rows: list[dict]) -> bool:
    failed = [row for row in rows
              if row.get("success") in (False, "False", "false") or row.get("itemType") == "exception"]
    if failed:
        details = [{key: row.get(key) for key in ("itemType", "name", "resultCode", "outerMessage")}
                   for row in failed]
        raise RuntimeError(
            "Correlated trace contains failed telemetry, including gateway dependencies without an agent ID. "
            "Successful agent spans alone do not prove a healthy Foundry trace: " + json.dumps(details)
        )
    successful = [row for row in rows if row.get("success") in (True, "True", "true")]
    agent_spans = [row for row in successful if row.get("agent") == "kernel-panic-aca"]
    operations = {row.get("operation") for row in agent_spans}
    tools = {row.get("tool") for row in agent_spans}
    requests = [row for row in successful if row.get("itemType") == "request"]
    return (
        {"invoke_agent", "chat", "execute_tool"} <= operations
        and {"sales_summary", "check_stock"} <= tools
        and any(row.get("name") == "POST /chat" for row in requests)
        and any(row.get("api_type") == "mcp-backend" for row in requests)
        and any(row.get("api") == "whisker-works-api" for row in requests)
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-telemetry", action="store_true")
    parser.add_argument("--telemetry-timeout", type=int, default=600)
    args = parser.parse_args()
    state_path = ROOT / ".build/external-agent.json"
    if not state_path.is_file():
        raise RuntimeError("Deploy Topic 6 first with scripts/deploy-external-agent.py --deploy")
    state = json.loads(state_path.read_text())
    settings = dotenv_values(ROOT / "agents/procode/.env")
    headers = {"Ocp-Apim-Subscription-Key": settings["APIM_GOLD_KEY"]}
    with DefaultAzureCredential() as credential, AIProjectClient(
        endpoint=state["projectEndpoint"], credential=credential, allow_preview=True,
    ) as project:
        definition = project.agents.get(state["agentName"]).versions.latest.definition
        if definition.kind != "external" or definition.otel_agent_id != state["otelAgentId"]:
            raise RuntimeError("Foundry registration does not match the runtime telemetry identity")
    print(f"PASS Foundry external registration: {state['agentName']}")
    with httpx.Client(timeout=150) as client:
        direct = client.post(state["containerAppUrl"] + "/chat", json={"prompt": PROMPT})
        if direct.status_code != 401:
            raise RuntimeError(f"Unauthenticated ACA backend was not protected: HTTP {direct.status_code}")
        print("PASS direct ACA request denied: HTTP 401 (Entra backend authentication)")
        missing = client.get(state["gatewayUrl"] + "/health")
        if missing.status_code != 401:
            raise RuntimeError(f"Missing APIM subscription was not denied: HTTP {missing.status_code}")
        print("PASS missing APIM subscription denied: HTTP 401")
        blocked = client.post(
            state["gatewayUrl"] + "/chat", json={"prompt": "Place a purchase order."},
            headers={**headers, "x-whisker-action": "write"},
        )
        if blocked.status_code != 403 or blocked.json().get("enforced_by") != "apim":
            raise RuntimeError(f"Write-mode request was not blocked by APIM: HTTP {blocked.status_code}")
        print("PASS write-mode request blocked by APIM: HTTP 403 (no model invocation)")
        health = client.get(state["gatewayUrl"] + "/health", headers=headers)
        health.raise_for_status()
        response = client.post(state["gatewayUrl"] + "/chat", json={"prompt": PROMPT}, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"Agent invocation failed: HTTP {response.status_code}; {response.text[:1000]}")
        result = response.json()
    validate_result(result)
    print("PASS actual sales-summary execution and APIM-governed inventory MCP call")
    print(result["answer"])
    print(f"Trace ID: {result['trace_id']}")
    print(f"Runtime: {state['containerAppUrl']}")
    if args.verify_telemetry:
        query = telemetry_query(result["trace_id"])
        print(f"Checking linked Application Insights ({state['appInsightsId']}):\n```kql\n{query}```", flush=True)
        deadline = time.monotonic() + args.telemetry_timeout
        previous_ids = None
        while True:
            completed = subprocess.run(
                ["az", "monitor", "app-insights", "query", "--subscription", state["subscriptionId"],
                 "--app", state["appInsightsAppId"], "--offset", "1h",
                 "--analytics-query", query, "--output", "json"],
                capture_output=True, text=True, check=True,
            )
            table = json.loads(completed.stdout)["tables"][0]
            rows = [dict(zip([column["name"] for column in table["columns"]], row)) for row in table["rows"]]
            complete = validate_telemetry(rows)
            current_ids = {(row["itemType"], row["id"]) for row in rows}
            if complete and current_ids == previous_ids:
                print(f"PASS agent and gateway telemetry ingested without failures: {len(rows)} correlated items")
                print(json.dumps(rows, indent=2))
                break
            previous_ids = current_ids if complete else None
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "Agent and gateway telemetry was not fully ingested and stable before the deadline; "
                    "do not claim observability passed"
                )
            time.sleep(20)


if __name__ == "__main__":
    main()
