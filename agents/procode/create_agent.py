"""Create (or add a new version of) the pro-code Whisker Works agent from agent.yaml.

Usage:
    python create_agent.py                 # uses agent.yaml
    python create_agent.py --model gpt-5-mini   # quick override for the "new model" demo
    python create_agent.py --name whiskers-concierge-pro-live --output-json agent-result.json
"""
import argparse
import json
import os
import pathlib
from urllib.parse import quote

import yaml
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import A2APreviewTool, A2ATool, AutoCodeInterpreterToolParam, CodeInterpreterTool, FileSearchTool, MCPTool, PromptAgentDefinition
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

HERE = pathlib.Path(__file__).parent
load_dotenv(HERE / ".env")


def get_or_create_vector_store(openai, name: str, files: list[str]):
    for vs in openai.vector_stores.list():
        if vs.name == name:
            print(f"Reusing vector store {vs.id} ({name})")
            return vs
    vs = openai.vector_stores.create(name=name)
    for rel in files:
        with open(HERE / rel, "rb") as fh:
            openai.vector_stores.files.upload_and_poll(vector_store_id=vs.id, file=fh)
        print(f"  uploaded {rel}")
    print(f"Created vector store {vs.id} ({name})")
    return vs


def build_mcp_tool(cfg: dict) -> MCPTool:
    gateway = os.environ["APIM_GATEWAY_URL"].rstrip("/")
    path = cfg.get("path", os.getenv("APIM_MCP_PATH", "whisker-mcp")).strip("/")
    kwargs = {
        "server_label": cfg.get("server_label", "whisker_store"),
        "server_url": f"{gateway}/{path}/mcp",
        "require_approval": cfg.get("require_approval", "never"),
    }
    if cfg.get("allowed_tools"):
        kwargs["allowed_tools"] = cfg["allowed_tools"]
    connection = cfg.get("project_connection_name", os.getenv("MCP_PROJECT_CONNECTION_NAME"))
    if connection:
        # Preferred: the APIM subscription key lives in a Foundry project connection, not in code.
        kwargs["project_connection_id"] = connection
    elif os.getenv("APIM_SUBSCRIPTION_KEY"):
        kwargs["headers"] = {"Ocp-Apim-Subscription-Key": os.environ["APIM_SUBSCRIPTION_KEY"]}
    return MCPTool(**kwargs)


def build_code_interpreter_tool(openai, cfg: dict) -> CodeInterpreterTool:
    paths = [HERE / rel for rel in cfg.get("files", [])]
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"Code Interpreter input file not found: {path}")
    file_ids = []
    for path in paths:
        with path.open("rb") as fh:
            uploaded = openai.files.create(file=fh, purpose="assistants")
        file_ids.append(uploaded.id)
        print(f"  uploaded Code Interpreter input {path.name}")
    return CodeInterpreterTool(container=AutoCodeInterpreterToolParam(file_ids=file_ids))


def build_a2a_tool(project, cfg: dict) -> A2APreviewTool | A2ATool:
    connection = project.connections.get(cfg["project_connection_name"])
    if cfg.get("agent_name"):
        name = quote(cfg["agent_name"], safe="")
        return A2ATool(
            base_url=f"{os.environ['FOUNDRY_PROJECT_ENDPOINT'].rstrip('/')}/agents/{name}/endpoint/protocols/a2a",
            project_connection_id=connection.id,
            a2a_version="1.0",
        )
    path = cfg["path"].strip("/")
    return A2APreviewTool(
        base_url=f"{os.environ['APIM_GATEWAY_URL'].rstrip('/')}/{path}",
        project_connection_id=connection.id,
        agent_card_path=f"/{path}/.well-known/agent-card.json",
        send_credentials_for_agent_card=True,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(HERE / "agent.yaml"))
    parser.add_argument("--model", help="Override the model from agent.yaml")
    parser.add_argument("--name", help="Override only the agent name; leave the source YAML unchanged")
    parser.add_argument("--output-json", type=pathlib.Path, help="Write the created name, version and model for clients")
    args = parser.parse_args()

    cfg = yaml.safe_load(pathlib.Path(args.config).read_text())
    model = args.model or cfg["model"]
    instructions = (HERE / cfg["instructions_file"]).read_text()

    project = AIProjectClient(endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"], credential=DefaultAzureCredential())
    openai = project.get_openai_client()

    tools = []
    if cfg.get("knowledge"):
        vs = get_or_create_vector_store(openai, cfg["knowledge"]["vector_store_name"], cfg["knowledge"]["files"])
        tools.append(FileSearchTool(vector_store_ids=[vs.id]))
    if cfg.get("code_interpreter", {}).get("enabled"):
        tools.append(build_code_interpreter_tool(openai, cfg["code_interpreter"]))
    if cfg.get("mcp", {}).get("enabled"):
        tools.append(build_mcp_tool(cfg["mcp"]))
    if cfg.get("a2a", {}).get("enabled"):
        tools.append(build_a2a_tool(project, cfg["a2a"]))
        if cfg["a2a"].get("instructions_file"):
            instructions += "\n\n" + (HERE / cfg["a2a"]["instructions_file"]).read_text()

    agent = project.agents.create_version(
        agent_name=args.name or cfg["name"],
        description=cfg.get("description"),
        definition=PromptAgentDefinition(model=model, instructions=instructions, tools=tools),
    )
    print(f"Agent ready: name={agent.name} version={agent.version} model={model}")
    if args.output_json:
        args.output_json.write_text(
            json.dumps({"name": agent.name, "version": str(agent.version), "model": model}) + "\n"
        )


if __name__ == "__main__":
    main()
