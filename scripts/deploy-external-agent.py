"""Deploy the optional Topic 6 runtime and register it in Foundry (preview).

Run from the repo's Python environment. Settings come from agents/procode/.env.
No existing hosted agent, APIM global policy, or Foundry connection is replaced.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import time
from urllib.parse import urlsplit

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import ExternalAgentDefinition
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from dotenv import dotenv_values
import httpx

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".build" / "external-agent.json"
AGENT_NAME = "kernel-panic-aca"


def az(*arguments: str):
    result = subprocess.run(
        ["az", *arguments, "--only-show-errors", "--output", "json"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout) if result.stdout.strip() else None


def resource_group(resource_id: str) -> str:
    parts = resource_id.split("/")
    return parts[parts.index("resourceGroups") + 1]


def register(project: AIProjectClient):
    try:
        existing = project.agents.get(AGENT_NAME)
    except ResourceNotFoundError:
        existing = None
    if existing is not None:
        definition = existing.versions.latest.definition
        if definition.kind != "external":
            raise RuntimeError(f"{AGENT_NAME} already exists and is not an external agent; refusing to overwrite")
        if definition.otel_agent_id == AGENT_NAME:
            print(f"Foundry external registration already matches: {AGENT_NAME}")
            return
    project.agents.create_version(
        agent_name=AGENT_NAME,
        description="Kernel Panic on Azure Container Apps. Read-only ops analyst; APIM enforces controls; Foundry observes.",
        definition=ExternalAgentDefinition(otel_agent_id=AGENT_NAME),
    )
    verified = project.agents.get(AGENT_NAME).versions.latest.definition
    if verified.kind != "external" or verified.otel_agent_id != AGENT_NAME:
        raise RuntimeError("External agent registration read-back did not match telemetry identity")
    print(f"Registered in Foundry: {AGENT_NAME} (external, preview)")


def wait_for_health(url: str, expected_status: int, headers: dict | None = None):
    deadline = time.monotonic() + 180
    with httpx.Client(timeout=15) as client:
        while True:
            response = client.get(url + "/health", headers=headers)
            if response.status_code == expected_status:
                if expected_status == 200 and response.json().get("status") != "purring":
                    raise RuntimeError("Gateway returned an unexpected health response")
                return
            transient = (502, 503, 504) + ((403, 500) if expected_status == 200 else ())
            if response.status_code not in transient or time.monotonic() >= deadline:
                raise RuntimeError(f"Endpoint did not become ready: HTTP {response.status_code}")
            print(f"Waiting for ACA authentication readiness: HTTP {response.status_code}", flush=True)
            time.sleep(5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deploy", action="store_true", help="Provision Azure resources, build, deploy and register.")
    parser.add_argument("--register-only", action="store_true", help="Register the external agent without provisioning.")
    parser.add_argument("--location", help="Defaults to the demo resource group's location.")
    parser.add_argument("--image-tag", help="Reuse an already-built registry image tag instead of rebuilding.")
    args = parser.parse_args()
    if args.deploy == args.register_only:
        parser.error("Choose exactly one of --deploy or --register-only")
    config = dotenv_values(ROOT / "agents/procode/.env")
    endpoint = config["FOUNDRY_PROJECT_ENDPOINT"]
    if not endpoint:
        raise ValueError("FOUNDRY_PROJECT_ENDPOINT is required")
    with DefaultAzureCredential() as credential, AIProjectClient(
        endpoint=endpoint, credential=credential, allow_preview=True,
    ) as project:
        if args.register_only:
            register(project)
            return
        subscription = config["AZURE_SUBSCRIPTION_ID"]
        group = config["RG"]
        apim_name = config["APIM_NAME"]
        apim_group = config["APIM_RG"]
        gold_key = config.get("APIM_GOLD_KEY") or config.get("APIM_SUBSCRIPTION_KEY")
        if not all((subscription, group, apim_name, apim_group, gold_key)):
            raise ValueError("Demo subscription, RG, APIM and Gold-key settings are required")
        account_name = urlsplit(endpoint).hostname.split(".")[0]
        accounts = az("cognitiveservices", "account", "list", "--subscription", subscription)
        account = next((item for item in accounts if item["name"] == account_name), None)
        if account is None:
            raise RuntimeError("Foundry account was not found in the configured demo subscription")
        connections = [item for item in project.connections.list() if item.type == "AppInsights"]
        if len(connections) != 1:
            raise RuntimeError("Expected exactly one Application Insights connection on the Foundry project")
        insights_id = connections[0].target
        insights = az("resource", "show", "--ids", insights_id)
        workspace_id = insights["properties"]["WorkspaceResourceId"]
        group_info = az("group", "show", "--subscription", subscription, "--name", group)
        apim = az("apim", "show", "--subscription", subscription, "--resource-group", apim_group,
                  "--name", apim_name)
        principal_id = apim["identity"]["principalId"]
        apim_identity = az("ad", "sp", "show", "--id", principal_id)
        display_name = f"{apim_name}-kernel-panic-aca"
        applications = az("ad", "app", "list", "--display-name", display_name)
        if len(applications) > 1:
            raise RuntimeError(f"Multiple Entra apps named {display_name}; choose one explicitly before deploying")
        application = applications[0] if applications else az(
            "ad", "app", "create", "--display-name", display_name,
            "--sign-in-audience", "AzureADMyOrg", "--requested-access-token-version", "2",
        )
        client_id = application["appId"]
        az("ad", "app", "update", "--id", client_id, "--identifier-uris", f"api://{client_id}")
        principals = az("ad", "sp", "list", "--filter", f"appId eq '{client_id}'")
        if not principals:
            az("ad", "sp", "create", "--id", client_id)
        parameters = {
            "location": args.location or group_info["location"],
            "foundryAccountName": account_name,
            "foundryResourceGroup": resource_group(account["id"]),
            "projectName": urlsplit(endpoint).path.rstrip("/").split("/")[-1],
            "appInsightsName": insights["name"],
            "monitoringResourceGroup": resource_group(insights_id),
            "workspaceName": workspace_id.split("/")[-1],
            "workspaceResourceGroup": resource_group(workspace_id),
            "apimName": apim_name, "apimResourceGroup": apim_group,
            "apimPrincipalId": principal_id, "apimClientId": apim_identity["appId"], "apiClientId": client_id,
            "apimSubscriptionKey": gold_key,
            "modelDeployment": config.get("CHAT_MODEL") or "gpt-4.1-mini",
        }
        print(f"Target: {subscription} / {group} / {parameters['location']}", flush=True)
        with TemporaryDirectory(prefix="whisker-11b-") as directory:
            path = Path(directory) / "parameters.json"

            def deploy():
                path.write_text(json.dumps({
                    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
                    "contentVersion": "1.0.0.0",
                    "parameters": {name: {"value": value} for name, value in parameters.items()},
                }))
                path.chmod(0o600)
                return az("deployment", "group", "create", "--subscription", subscription,
                          "--resource-group", group, "--name", "whisker-topic-11b",
                          "--template-file", str(ROOT / "infra/external-agent.bicep"),
                          "--parameters", f"@{path}", "--query", "properties.outputs")

            print("Provisioning additive Container Apps environment, identity and registry...", flush=True)
            bootstrap = deploy()
            registry = bootstrap["registryName"]["value"]
            tag = args.image_tag or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            if not args.image_tag:
                print(f"Building {registry}/kernel-panic-aca:{tag} with a source allowlist...", flush=True)
                subprocess.run(
                    ["az", "acr", "build", "--subscription", subscription, "--registry", registry,
                     "--image", f"kernel-panic-aca:{tag}", "--file", "agents/container-app/Dockerfile", "."],
                    cwd=ROOT, check=True,
                )
            parameters["imageTag"] = tag
            print("Deploying runtime, Entra backend authentication and scoped APIM API...", flush=True)
            outputs = deploy()
        state = {name: value["value"] for name, value in outputs.items()}
        state.update({
            "subscriptionId": subscription, "resourceGroup": group,
            "agentName": AGENT_NAME, "otelAgentId": AGENT_NAME,
            "projectEndpoint": endpoint, "appInsightsId": insights_id,
            "appInsightsAppId": insights["properties"]["AppId"],
            "apiClientId": client_id, "imageTag": tag,
        })
        STATE.parent.mkdir(exist_ok=True)
        STATE.write_text(json.dumps(state, indent=2) + "\n")
        if args.image_tag:
            revision = az("containerapp", "show", "--subscription", subscription,
                          "--resource-group", group, "--name", state["containerAppName"],
                          "--query", "properties.latestRevisionName")
            az("containerapp", "revision", "restart", "--subscription", subscription,
               "--resource-group", group, "--name", state["containerAppName"], "--revision", revision)
        wait_for_health(state["containerAppUrl"], 401)
        wait_for_health(state["gatewayUrl"], 200, {"Ocp-Apim-Subscription-Key": gold_key})
        register(project)
        print(f"Gateway: {state['gatewayUrl']}")
        print(f"Runtime: {state['containerAppUrl']} (Entra authentication; APIM principal only)")
        print("Next: python scripts/test-external-agent.py --verify-telemetry")


if __name__ == "__main__":
    main()
