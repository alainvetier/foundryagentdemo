"""Enable the deployed specialist's authenticated Foundry A2A endpoint."""
import os
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    A2AProtocolConfiguration,
    AgentCard,
    AgentCardSkill,
    AgentEndpointConfig,
    ProtocolConfiguration,
    ResponsesProtocolConfiguration,
)
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv


def main() -> None:
    here = Path(__file__).resolve().parent
    load_dotenv(here / ".env")
    load_dotenv(here.parent / "procode" / ".env")
    with DefaultAzureCredential() as credential, AIProjectClient(
        endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"], credential=credential,
    ) as project:
        agent = project.agents.update_details(
            agent_name="purrfessor-nibbles",
            agent_endpoint=AgentEndpointConfig(
                protocol_configuration=ProtocolConfiguration(
                    responses=ResponsesProtocolConfiguration(),
                    a2a=A2AProtocolConfiguration(),
                ),
            ),
            agent_card=AgentCard(
                version="1.0",
                description="Purrfessor Nibbles, Whisker Works' cat-food specialist. General guidance, not veterinary care.",
                skills=[AgentCardSkill(
                    id="cat-food", name="Cat food and feeding",
                    description="Food and treat selection, life stages, labels and general feeding guidance.",
                )],
            ),
        )
    print(f"Authenticated incoming A2A enabled: {agent.name}")


if __name__ == "__main__":
    main()
