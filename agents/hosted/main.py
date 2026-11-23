"""Kernel Panic - Whisker Works' Head of DevOps & ops analyst cat.

A Foundry *hosted* agent built with Microsoft Agent Framework:
- custom Python tools running inside the container (sales analytics, purchase orders with human approval)
- Whisker Works Store tools through the APIM-governed MCP server (Layer 2)
"""
from __future__ import annotations

import os
import uuid
from contextlib import AsyncExitStack
from types import TracebackType
from typing import Annotated

from agent_framework import Agent, tool
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.ai.agentserver.core import AgentConfig, get_request_context
from azure.identity.aio import AzureCliCredential, ManagedIdentityCredential
from dotenv import load_dotenv
from pydantic import Field
from sales import summarize_sales

INSTRUCTIONS = """You are Kernel Panic, the black-cat Head of DevOps at Whisker Works, a store run by techie cats.
You help store staff with operations: sales analysis, stock checks and restocking.
- Use sales_summary for any sales, revenue or returns question. Never invent numbers.
- Use the whisker_store tools for live product, stock and order data.
- When stock is out or low (under 5) and sales are healthy, propose a restock quantity and use
  create_purchase_order only after explaining why. Staff must approve every purchase order.
- Be concise, use bullet points, and add at most one DevOps pun."""

@tool(approval_mode="never_require")
def sales_summary(
    group_by: Annotated[str, Field(description="Group results by 'month', 'category' or 'product'.")] = "category",
    month: Annotated[str | None, Field(description="Optional month filter, format YYYY-MM (2026-04 to 2026-09).")] = None,
) -> str:
    """Summarise Whisker Works sales (units, revenue, returns) from April to September 2026."""
    return summarize_sales(group_by, month)


@tool(approval_mode="always_require")
def create_purchase_order(
    product_id: Annotated[str, Field(description="Product ID, e.g. WW-004.")],
    quantity: Annotated[int, Field(ge=1, le=500, description="Units to order from the supplier.")],
) -> str:
    """Create a supplier purchase order to restock a product. Requires human approval."""
    return f"Purchase order PO-{uuid.uuid4().hex[:6].upper()} created: {quantity} x {product_id.upper()}, ETA 5 business days."


def create_agent() -> Agent:
    """Build the client and tools per request (hosted pattern: no state kept on the agent)."""
    credential = (
        ManagedIdentityCredential(client_id=os.environ.get("FOUNDRY_AGENT_INSTANCE_CLIENT_ID"))
        if AgentConfig.from_env().is_hosted
        else AzureCliCredential()
    )

    class RequestClient(FoundryChatClient):
        async def __aenter__(self) -> RequestClient:
            return self

        async def __aexit__(
            self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None
        ) -> None:
            async with AsyncExitStack() as cleanup:
                cleanup.push_async_callback(credential.close)
                cleanup.push_async_callback(self.project_client.close)
                cleanup.push_async_callback(self.client.close)

    client = RequestClient(
        project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        model=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
        credential=credential,
        default_headers=get_request_context().platform_headers(),
    )

    tools = [sales_summary, create_purchase_order]
    gateway, key = os.environ.get("APIM_GATEWAY_URL"), os.environ.get("APIM_SUBSCRIPTION_KEY")
    if gateway and key:
        tools.append(
            client.get_mcp_tool(
                name="whisker_store",
                url=f"{gateway.rstrip('/')}/{os.environ.get('APIM_MCP_PATH', 'whisker-mcp')}/mcp",
                headers={"Ocp-Apim-Subscription-Key": key, "x-agent-id": "kernel-panic-hosted"},
                approval_mode="never_require",
            )
        )

    return Agent(client=client, instructions=INSTRUCTIONS, tools=tools)


def main() -> None:
    load_dotenv()
    server = ResponsesHostServer(agent=create_agent, history_source="agent_server")
    server.run()


if __name__ == "__main__":
    main()
