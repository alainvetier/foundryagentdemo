"""Generate representative Foundry conversations and traces before the demo."""

import argparse
import os
import pathlib

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "agents" / "procode" / ".env")

PROMPTS = [
    "What's your return policy if my cat ignores the new bed?",
    "My cat sleeps on my laptop. What do you recommend and how much is it?",
    "Is the Premium Cardboard Box in stock?",
    "Can I order lilies for my cat's birthday?",
]


def agent_reference(name: str) -> dict[str, str]:
    return {"name": name, "type": "agent_reference"}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create Foundry conversations and trace spans for the Whisker Works demo."
    )
    parser.add_argument(
        "--agents",
        nargs="+",
        default=["whiskers-concierge"],
        help="Agent names to invoke (default: whiskers-concierge).",
    )
    args = parser.parse_args()

    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
    if not endpoint:
        parser.error("FOUNDRY_PROJECT_ENDPOINT is missing; run scripts/deploy.sh first")

    project = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
    openai = project.get_openai_client()

    for agent_name in args.agents:
        conversation = openai.conversations.create()
        print(f"{agent_name}: conversation {conversation.id}")
        for prompt in PROMPTS:
            response = openai.responses.create(
                conversation=conversation.id,
                input=prompt,
                extra_body={"agent_reference": agent_reference(agent_name)},
            )
            print(f"  response {response.id}: {prompt}")

    print("Trace traffic submitted. Allow several minutes for Application Insights ingestion, then refresh Traces.")


if __name__ == "__main__":
    main()
