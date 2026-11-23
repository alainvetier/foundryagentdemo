"""Interactive chat with a Foundry agent. Shows which tools were used on every turn.

Usage:
    python chat.py                              # latest version of whiskers-concierge-pro
    python chat.py --agent whiskers-concierge   # the low-code agent created in the portal
    python chat.py --version 1                  # pin a specific version
"""
import argparse
import os
import pathlib

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from openai.types.responses.response_input_param import McpApprovalResponse

load_dotenv(pathlib.Path(__file__).parent / ".env")


def agent_ref(name: str, version: str | None) -> dict:
    ref = {"name": name, "type": "agent_reference"}
    if version:
        ref["version"] = version
    return ref


def describe_tools(response) -> str:
    used = []
    for item in response.output:
        if item.type == "mcp_call":
            used.append(f"mcp:{item.server_label}.{item.name}")
        elif item.type == "file_search_call":
            used.append("file_search")
        elif item.type not in ("message", "reasoning", "mcp_list_tools"):
            used.append(item.type)
    return ", ".join(used) or "none"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", default="whiskers-concierge-pro")
    parser.add_argument("--version")
    args = parser.parse_args()

    project = AIProjectClient(endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"], credential=DefaultAzureCredential())
    openai = project.get_openai_client()
    conversation = openai.conversations.create()
    ref = agent_ref(args.agent, args.version)
    print(f"Chatting with {args.agent} (version: {args.version or 'latest'}). Ctrl+C to quit.\n")

    while True:
        try:
            text = input("you > ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not text:
            continue
        response = openai.responses.create(conversation=conversation.id, input=text, extra_body={"agent_reference": ref})

        # Human-in-the-loop for MCP tools configured with require_approval
        approvals = []
        for item in response.output:
            if item.type == "mcp_approval_request":
                ok = input(f"  approve {item.server_label}.{item.name}({item.arguments})? [y/N] ").lower() == "y"
                approvals.append(McpApprovalResponse(type="mcp_approval_response", approve=ok, approval_request_id=item.id))
        if approvals:
            response = openai.responses.create(input=approvals, previous_response_id=response.id, extra_body={"agent_reference": ref})

        print(f"whiskers > {response.output_text}")
        tokens = response.usage.total_tokens if response.usage else "?"
        print(f"  [tools: {describe_tools(response)} | tokens: {tokens}]\n")


if __name__ == "__main__":
    main()
