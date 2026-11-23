"""Kernel Panic on ACA: standalone, read-only, with Foundry-correlated telemetry."""

import asyncio
from contextlib import asynccontextmanager
import json
import logging
import os
from typing import Literal
import uuid

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.monitor.opentelemetry import configure_azure_monitor
from fastapi import FastAPI, HTTPException
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from openai import APIError
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from pydantic import BaseModel, ConfigDict, Field

from sales import summarize_sales

AGENT_NAME = "kernel-panic-aca"
ATTRIBUTES = {
    "gen_ai.agent.id": AGENT_NAME,
    "gen_ai.agent.name": AGENT_NAME,
    "whisker.runtime": "azure-container-apps",
}
INSTRUCTIONS = """You are Kernel Panic, Whisker Works' black-cat operations analyst.
Use sales_summary for sales questions and check_stock for current stock. Never invent results.
This standalone demo is read-only. You cannot place orders or modify inventory.
When asked for September sales use 2026-09. Keep answers to three short bullets.
If a tool fails, report the failure rather than guessing."""
logger = logging.getLogger(__name__)
tracer = trace.get_tracer("whisker.kernel-panic-aca")


class SalesArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group_by: Literal["month", "category", "product"] = "category"
    month: str | None = Field(default=None, pattern=r"^2026-0[4-9]$")


class StockArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: str = Field(pattern=r"^WW-\d{3}$")


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=2000)
    mode: Literal["read-only"] = "read-only"


def function_tool(name: str, description: str, arguments: type[BaseModel]) -> dict:
    return {"type": "function", "name": name, "description": description,
            "parameters": arguments.model_json_schema()}


TOOLS = [
    function_tool("sales_summary", "Summarize April to September 2026 sales.", SalesArguments),
    function_tool("check_stock", "Check live Store inventory through the APIM MCP gateway.", StockArguments),
]


async def check_stock(product_id: str) -> dict:
    url = f"{os.environ['APIM_GATEWAY_URL'].rstrip('/')}/{os.getenv('APIM_MCP_PATH', 'whisker-mcp')}/mcp"
    headers = {"Ocp-Apim-Subscription-Key": os.environ["APIM_SUBSCRIPTION_KEY"],
               "x-agent-id": AGENT_NAME}
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            discovered = await session.list_tools()
            inventory = next((tool.name for tool in discovered.tools
                              if tool.name in ("checkStockLevel", "checkInventory")), None)
            if inventory is None:
                raise RuntimeError("APIM MCP exposes no supported inventory tool")
            result = await session.call_tool(inventory, {"productId": product_id})
            if result.isError:
                raise RuntimeError("APIM MCP inventory tool returned an error")
            payload = result.structuredContent
            if payload is None:
                payload = json.loads("\n".join(
                    item.text for item in result.content if item.type == "text"
                ))
            if (not isinstance(payload, dict) or payload.get("productId") != product_id
                    or type(payload.get("stock")) is not int or payload["stock"] < 0
                    or payload.get("status") not in ("in_stock", "low_stock", "out_of_stock")):
                raise RuntimeError("APIM MCP inventory result has an invalid shape")
            return {"mcp_tool": inventory, "inventory": payload}


def execute_tool(name: str, arguments: str) -> dict:
    with tracer.start_as_current_span(
        f"execute_tool {name}", attributes={**ATTRIBUTES, "gen_ai.operation.name": "execute_tool",
                                           "gen_ai.tool.name": name},
    ):
        if name == "sales_summary":
            args = SalesArguments.model_validate_json(arguments)
            return {"summary": summarize_sales(args.group_by, args.month)}
        if name == "check_stock":
            args = StockArguments.model_validate_json(arguments)
            return asyncio.run(check_stock(args.product_id))
        raise ValueError(f"Tool is not allowed in the read-only agent: {name}")


def run_agent(client, prompt: str, model: str) -> dict:
    messages = [{"role": "user", "content": prompt}]
    evidence = []
    for _ in range(4):
        with tracer.start_as_current_span(
            f"chat {model}", attributes={**ATTRIBUTES, "gen_ai.operation.name": "chat",
                                        "gen_ai.provider.name": "azure.ai.openai",
                                        "gen_ai.request.model": model},
        ) as span:
            response = client.responses.create(
                model=model, instructions=INSTRUCTIONS, input=messages,
                tools=TOOLS, max_output_tokens=1200, store=False,
            )
            span.set_attribute("gen_ai.response.id", response.id)
            if response.usage:
                span.set_attribute("gen_ai.usage.input_tokens", response.usage.input_tokens)
                span.set_attribute("gen_ai.usage.output_tokens", response.usage.output_tokens)
        if response.status != "completed":
            raise RuntimeError(f"Model response did not complete: {response.status}")
        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            if not response.output_text.strip():
                raise RuntimeError("Model returned no answer")
            return {"answer": response.output_text, "tool_calls": evidence, "response_id": response.id}
        messages.extend(item.model_dump(exclude_none=True) for item in response.output)
        for call in calls:
            result = execute_tool(call.name, call.arguments)
            evidence.append({"name": call.name, "arguments": json.loads(call.arguments), "result": result})
            messages.append({"type": "function_call_output", "call_id": call.call_id,
                             "output": json.dumps(result)})
    raise RuntimeError("Agent exceeded the four-round tool-call limit")


@asynccontextmanager
async def lifespan(app: FastAPI):
    for name in ("FOUNDRY_PROJECT_ENDPOINT", "AZURE_AI_MODEL_DEPLOYMENT_NAME",
                 "APIM_GATEWAY_URL", "APIM_SUBSCRIPTION_KEY", "APPLICATIONINSIGHTS_CONNECTION_STRING"):
        if not os.environ.get(name):
            raise RuntimeError(f"Missing required setting: {name}")
    configure_azure_monitor(
        connection_string=os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"],
        sampling_ratio=1.0,
        disable_offline_storage=True,
    )
    yield
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        provider.force_flush()


app = FastAPI(title="Kernel Panic - external ACA agent", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "purring", "agent": AGENT_NAME, "runtime": "azure-container-apps"}


@app.post("/chat")
def chat(request: ChatRequest):
    conversation = str(uuid.uuid4())
    with tracer.start_as_current_span(
        f"invoke_agent {AGENT_NAME}",
        attributes={**ATTRIBUTES, "gen_ai.operation.name": "invoke_agent",
                    "gen_ai.conversation.id": conversation,
                    "gen_ai.input.messages": json.dumps([
                        {"role": "user", "parts": [{"type": "text", "content": request.prompt}]}
                    ])},
    ) as span:
        trace_id = f"{span.get_span_context().trace_id:032x}"
        try:
            with DefaultAzureCredential() as credential, AIProjectClient(
                endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"], credential=credential,
            ) as project, project.get_openai_client() as client:
                result = run_agent(client, request.prompt, os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"])
            span.set_attribute("gen_ai.response.id", result["response_id"])
            span.set_attribute("gen_ai.output.messages", json.dumps([
                {"role": "assistant", "parts": [{"type": "text", "content": result["answer"]}]}
            ]))
        except (APIError, RuntimeError, ValueError, ExceptionGroup) as error:
            logger.exception("External agent failed; trace_id=%s", trace_id)
            raise HTTPException(502, detail=f"Agent or tool failed; trace_id={trace_id}") from error
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider) and not provider.force_flush(timeout_millis=10000):
        logger.error("Telemetry flush timed out; trace_id=%s", trace_id)
        raise HTTPException(503, detail=f"Telemetry export timed out; trace_id={trace_id}")
    return {"agent": AGENT_NAME, "runtime": "azure-container-apps", "trace_id": trace_id,
            "conversation_id": conversation, **result}
