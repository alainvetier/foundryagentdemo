"""Run Kernel Panic locally with the existing demo settings, without changing Azure."""

import argparse
from collections.abc import Mapping
import os
from pathlib import Path
import sys

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
HOSTED = ROOT / "agents" / "hosted"
SETTINGS = ROOT / "agents" / "procode" / ".env"


def local_environment(settings: Mapping[str, str | None]) -> dict[str, str]:
    sources = {
        "FOUNDRY_PROJECT_ENDPOINT": "FOUNDRY_PROJECT_ENDPOINT",
        "AZURE_AI_MODEL_DEPLOYMENT_NAME": "CHAT_MODEL",
        "APIM_GATEWAY_URL": "APIM_GATEWAY_URL",
        "APIM_SUBSCRIPTION_KEY": "APIM_GOLD_KEY",
    }
    missing = [source for source in sources.values() if not settings.get(source)]
    if missing:
        raise ValueError(f"Missing settings in {SETTINGS}: {', '.join(missing)}")
    environment = {}
    for target, source in sources.items():
        value = settings[source]
        if value is None:
            raise ValueError(f"Missing setting: {source}")
        environment[target] = value
    environment["APIM_MCP_PATH"] = settings.get("APIM_MCP_PATH") or "whisker-mcp"
    return environment


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate settings without starting the server.")
    args = parser.parse_args()
    if not SETTINGS.is_file():
        raise FileNotFoundError(f"Run the demo environment setup first: {SETTINGS} is missing.")
    environment = local_environment(dotenv_values(SETTINGS))
    print("Local Kernel Panic settings ready: existing model and APIM Gold MCP; credentials hidden.", flush=True)
    print(f"Local Python: {sys.executable}", flush=True)
    if args.check:
        return
    if os.environ.get("FOUNDRY_HOSTING_ENVIRONMENT"):
        raise RuntimeError("This launcher is for local debugging, not a Foundry-hosted environment.")
    os.environ.update(environment)
    os.environ["AGENTSERVER_STATE_ROOT"] = str(ROOT / ".build" / "agent-inspector")
    os.chdir(HOSTED)
    sys.path.insert(0, str(HOSTED))
    from agent_framework_foundry_hosting import ResponsesHostServer
    from main import create_agent

    server = ResponsesHostServer(agent=create_agent, history_source="agent_server")
    server.run(host="127.0.0.1", port=8088)


if __name__ == "__main__":
    main()
