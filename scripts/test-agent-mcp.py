"""Read-only agent -> APIM -> MCP smoke tests. Never approves or places orders."""

import argparse
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

import httpx
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from openai import APIError, BadRequestError, RateLimitError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents/procode"))
from compare_models import throttle_retry_delay

load_dotenv(ROOT / "agents/procode/.env")

STORE_CASES = (
    ("catalog", ("listProducts", "listOrSearchProducts"),
     "Use only the Store MCP catalog tool to list products. Do not filter the catalog."),
    ("product", ("getProduct", "getAProduct"),
     "Use only the Store MCP product-detail tool to retrieve WW-001."),
    ("inventory", ("checkInventory", "checkStockLevel"),
     "Use only the Store MCP inventory tool to check live stock of WW-001."),
    ("order", ("getOrder", "getOrderStatus"),
     "Use only the Store MCP order-status tool to retrieve ORD-1002."),
    ("fact", ("getRandomCatFact", "getARandomCatFact"),
     "Use only the Store MCP random cat fact tool to retrieve one fact."),
)
LEARN_CASES = (
    ("learn-search", ("microsoft_docs_search",),
     "Use microsoft_docs_search to find the Azure API Management llm-token-limit policy reference."),
    ("learn-fetch", ("microsoft_docs_fetch",),
     "Use microsoft_docs_fetch to read https://learn.microsoft.com/azure/api-management/llm-token-limit-policy ."),
    ("learn-code", ("microsoft_code_sample_search",),
     "Use microsoft_code_sample_search to find Python BlobServiceClient DefaultAzureCredential code samples."),
)


class CheckFailed(RuntimeError):
    pass


def decode_output(output):
    if not output:
        raise CheckFailed("MCP call returned no output")
    try:
        value = json.loads(output) if isinstance(output, str) else output
    except json.JSONDecodeError:
        return output
    if isinstance(value, dict) and (value.get("isError") or value.get("error")):
        raise CheckFailed("MCP result contains a tool error")
    if isinstance(value, dict) and "content" in value:
        content = value["content"]
        if not isinstance(content, list):
            raise CheckFailed("MCP result has invalid content")
        return decode_output("\n".join(
            item.get("text", "") for item in content if item.get("type") == "text"
        ))
    return value


def check_payload(case, payload):
    if case == "catalog":
        if not isinstance(payload, list) or not any(
            isinstance(item, dict) and item.get("id") == "WW-001" for item in payload
        ):
            raise CheckFailed("Catalog result does not contain WW-001")
    elif case in ("product", "inventory", "order", "fact"):
        if not isinstance(payload, dict):
            raise CheckFailed(f"{case} result is not a JSON object")
        if case == "product" and (
            payload.get("id") != "WW-001" or not payload.get("name")
            or not isinstance(payload.get("price"), (int, float))
        ):
            raise CheckFailed("Product result is missing WW-001, name or price")
        if case == "inventory" and (
            payload.get("productId") != "WW-001"
            or type(payload.get("stock")) is not int or payload["stock"] < 0
            or payload.get("status") not in ("in_stock", "low_stock", "out_of_stock")
        ):
            raise CheckFailed("Inventory result has invalid product, stock or status")
        if case == "order" and (
            payload.get("orderId") != "ORD-1002"
            or payload.get("status") not in ("processing", "shipped", "delivered")
        ):
            raise CheckFailed("Order result has invalid ID or status")
        if case == "fact" and not isinstance(payload.get("fact"), str):
            raise CheckFailed("Cat fact result is missing its fact")
        if case == "fact" and not payload["fact"].strip():
            raise CheckFailed("Cat fact is empty")
    elif not payload or (isinstance(payload, str) and not payload.strip()):
        raise CheckFailed("Learn tool returned no content")
    elif case == "learn-search" and "learn.microsoft.com/" not in str(payload):
        raise CheckFailed("Learn result contains no official documentation URL")
    elif case == "learn-fetch" and "llm-token-limit" not in str(payload).lower():
        raise CheckFailed("Fetched content does not contain the requested policy")


def check_response(response, case, names):
    if response.get("status") != "completed" or response.get("error"):
        raise CheckFailed("Agent response did not complete successfully")
    calls = []
    for item in response.get("output", []):
        if item["type"] == "mcp_approval_request":
            raise CheckFailed("Unexpected approval request; no approval was submitted")
        if item["type"] != "mcp_call":
            continue
        if item.get("status") != "completed" or item.get("error"):
            raise CheckFailed(f"MCP call {item.get('name')} failed")
        if item.get("name") not in names:
            raise CheckFailed("Agent called a tool outside this read-only test case")
        if case == "learn-fetch":
            try:
                arguments = json.loads(item.get("arguments") or "{}")
                url = urlsplit(arguments.get("url", ""))
            except (TypeError, ValueError, AttributeError):
                raise CheckFailed("Learn fetch has invalid arguments") from None
            if (url.scheme != "https" or url.hostname != "learn.microsoft.com"
                    or not url.path.rstrip("/").endswith("/llm-token-limit-policy")):
                raise CheckFailed("Learn fetch did not request the official policy URL")
        check_payload(case, decode_output(item.get("output")))
        calls.append(item["name"])
    if not calls:
        raise CheckFailed("No actual MCP call; assistant text is not proof of execution")
    return calls


def invoke(client, name, version, prompt, deadline):
    reference = {"name": name, "type": "agent_reference"}
    if version:
        reference["version"] = version
    for attempt in range(2):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CheckFailed("Smoke-test time budget exhausted")
        try:
            return client.responses.create(
                input=prompt + " Make a real tool call, not simulated JSON. Never place or modify an order. "
                "Do not use other tools. Report tool failures rather than guessing. Keep the answer brief.",
                extra_body={"agent_reference": reference},
                timeout=min(90, remaining),
            ).model_dump()
        except (BadRequestError, RateLimitError) as error:
            delay = throttle_retry_delay(error, attempt)
            if delay is None or attempt:
                raise
            delay = max(61, delay)
            if time.monotonic() + delay >= deadline:
                raise CheckFailed("Rate limit would exceed the smoke-test time budget") from None
            print(f"  Rate limited; waiting {delay:g}s for the governance window.", flush=True)
            time.sleep(delay)


def discover_orders(gateway, key, deadline=None):
    """Perform discovery only: this function never sends tools/call."""
    url = gateway.rstrip("/") + "/whisker-mcp-orders/mcp"
    if deadline is None:
        deadline = time.monotonic() + 90
    with httpx.Client(timeout=30, headers={
        "Accept": "application/json, text/event-stream", "Ocp-Apim-Subscription-Key": key,
    }) as client:
        def request(method, params, request_id):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CheckFailed("Orders discovery time budget exhausted")
            response = client.post(url, json={
                "jsonrpc": "2.0", "id": request_id, "method": method, "params": params,
            }, timeout=min(30, remaining))
            response.raise_for_status()
            if response.headers.get("mcp-session-id"):
                client.headers["mcp-session-id"] = response.headers["mcp-session-id"]
            if response.headers.get("content-type", "").startswith("text/event-stream"):
                messages = [
                    json.loads(line[5:].strip()) for line in response.text.splitlines()
                    if line.startswith("data:")
                ]
                body = next((item for item in messages if item.get("id") == request_id), None)
            else:
                body = response.json()
            if not isinstance(body, dict) or body.get("error") or body.get("id") != request_id:
                raise CheckFailed(f"Orders MCP {method} returned an invalid/error response")
            return body["result"]

        initialized = request("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "whisker-smoke-test", "version": "1.0"},
        }, 1)
        client.headers["MCP-Protocol-Version"] = initialized["protocolVersion"]
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CheckFailed("Orders discovery time budget exhausted")
        notification = client.post(
            url, json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            timeout=min(30, remaining),
        )
        notification.raise_for_status()
        tools = request("tools/list", {}, 2).get("tools", [])
        if not tools or not any(tool["name"] in ("placeOrder", "placeAnOrder") for tool in tools):
            raise CheckFailed("Orders MCP did not discover an order tool")
        return [tool["name"] for tool in tools]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--low-code-agent", default="whiskers-concierge")
    parser.add_argument("--pro-code-agent", default="whiskers-concierge-pro")
    parser.add_argument("--learn-agent", default="whisker-learn-guide")
    for agent in ("low-code", "pro-code", "learn"):
        parser.add_argument(f"--{agent}-version", help="Pin a numeric version; otherwise use latest")
    parser.add_argument("--scope", choices=("all", "store", "learn"), default="all")
    parser.add_argument("--orders-discovery", action="store_true", help="Optional server; NEVER executes order tools")
    parser.add_argument("--pause", type=float, default=15, help="Seconds between cases (default: 15)")
    parser.add_argument("--budget", type=float, default=600, help="Overall request/retry budget in seconds")
    args = parser.parse_args()
    if args.pause < 0 or args.budget <= 0:
        parser.error("--pause must be non-negative and --budget must be positive")
    for agent in ("low_code", "pro_code", "learn"):
        version = getattr(args, agent + "_version")
        if version and not version.isdigit():
            parser.error("Agent versions must be numeric")
    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
    if not endpoint:
        parser.error("FOUNDRY_PROJECT_ENDPOINT is missing from local settings")

    cases = []
    if args.scope in ("all", "store"):
        for name, version in (
            (args.low_code_agent, args.low_code_version), (args.pro_code_agent, args.pro_code_version),
        ):
            cases.extend((name, version, *case) for case in STORE_CASES)
    if args.scope in ("all", "learn"):
        cases.extend((args.learn_agent, args.learn_version, *case) for case in LEARN_CASES)
    deadline = time.monotonic() + args.budget
    failed = 0
    passed = 0
    print("Read-only MCP validation: no agent definitions changed; no orders approved.", flush=True)
    with DefaultAzureCredential() as credential, AIProjectClient(endpoint=endpoint, credential=credential) as project:
        with project.get_openai_client().with_options(max_retries=0) as client:
            for index, (name, version, case, names, prompt) in enumerate(cases):
                if index:
                    time.sleep(min(args.pause, max(0, deadline - time.monotonic())))
                print(f"[{index + 1}/{len(cases)}] {name}: {case}", flush=True)
                response = None
                try:
                    response = invoke(client, name, version, prompt, deadline)
                    calls = check_response(response, case, names)
                    actual_version = (response.get("agent_reference") or {}).get("version", version or "latest")
                    print(f"  PASS v{actual_version}: {', '.join(calls)}; response={response['id']}", flush=True)
                    passed += 1
                except CheckFailed as error:
                    failed += 1
                    evidence = f"; response={response['id']}" if response else ""
                    print(f"  FAIL: {error}{evidence}", flush=True)
                except APIError as error:
                    failed += 1
                    print(f"  FAIL: {type(error).__name__}; HTTP {getattr(error, 'status_code', 'n/a')}", flush=True)
                if time.monotonic() >= deadline:
                    print("FAIL: time budget exhausted; remaining cases NOT TESTED.", flush=True)
                    return 1
    if args.orders_discovery:
        try:
            tools = discover_orders(
                os.environ["APIM_GATEWAY_URL"], os.environ["APIM_SUBSCRIPTION_KEY"], deadline,
            )
            print(f"PASS orders discovery ONLY: {', '.join(tools)}; no tools/call sent.", flush=True)
        except (CheckFailed, httpx.HTTPError, KeyError, ValueError) as error:
            failed += 1
            print(f"FAIL orders discovery: {type(error).__name__}; no order execution attempted.", flush=True)
    else:
        print("SKIP optional orders MCP (use --orders-discovery for discovery only).", flush=True)
    print(f"Agent cases: {passed}/{len(cases)} passed; {failed} failed checks. "
          "Order execution is deliberately NOT TESTED.", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
