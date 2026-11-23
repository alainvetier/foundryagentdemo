"""Purrfessor Nibbles, Whisker Works' hosted cat-food specialist."""
from __future__ import annotations

import os
from contextlib import AsyncExitStack
from pathlib import Path
from types import TracebackType

from agent_framework import Agent, tool
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.ai.agentserver.core import AgentConfig, get_request_context
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent


@tool(approval_mode="never_require")
def cat_food_guide() -> str:
    """Read the sourced Whisker Works food catalog and general feeding guidance (not live inventory)."""
    return (HERE / "food-guide.md").read_text(encoding="utf-8")


def create_agent() -> Agent:
    """Create request-scoped clients; conversation history belongs to the host."""
    hosted = AgentConfig.from_env().is_hosted
    identity = os.environ.get("FOUNDRY_AGENT_INSTANCE_CLIENT_ID")
    if hosted and not identity:
        raise RuntimeError("Hosted cat-food agent requires FOUNDRY_AGENT_INSTANCE_CLIENT_ID")
    credential = DefaultAzureCredential(
        managed_identity_client_id=identity,
        # Keep the repository's DefaultAzureCredential convention, but make hosted auth deterministic.
        exclude_environment_credential=hosted,
        exclude_workload_identity_credential=hosted,
        exclude_shared_token_cache_credential=hosted,
        exclude_visual_studio_code_credential=hosted,
        exclude_cli_credential=hosted,
        exclude_powershell_credential=hosted,
        exclude_developer_cli_credential=hosted,
        exclude_broker_credential=hosted,
    )

    class RequestClient(FoundryChatClient):
        async def __aenter__(self) -> RequestClient:
            return self

        async def __aexit__(
            self, exc_type: type[BaseException] | None,
            exc_value: BaseException | None, traceback: TracebackType | None,
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
    return Agent(
        name="Purrfessor Nibbles",
        client=client,
        instructions=(HERE / "instructions.md").read_text(encoding="utf-8"),
        tools=[cat_food_guide],
        default_options={"store": False},
    )


def main() -> None:
    hosted = AgentConfig.from_env().is_hosted
    if not hosted:
        load_dotenv(HERE / ".env")
        load_dotenv(HERE.parent / "procode" / ".env")
        if not os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME") and os.getenv("CHAT_MODEL"):
            os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"] = os.environ["CHAT_MODEL"]
    ResponsesHostServer(agent=create_agent, history_source="agent_server").run(
        host="0.0.0.0" if hosted else "127.0.0.1",
    )


if __name__ == "__main__":
    main()
