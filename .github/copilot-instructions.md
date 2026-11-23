# Copilot instructions - Whisker Works demo

This repo is a demo kit for Microsoft Foundry Agent Service + Azure API Management as an AI gateway.
Theme: **Whisker Works**, a retail store run by techie cats. Keep the playful cat theme in names, sample data and copy.
Write documentation as self-paced instructions with prerequisites and verification steps. Do not add
topic-duration estimates, audience directions, or presentation scripts. Keep technical timeouts, rate limits,
and required propagation waits explicit.

## Conventions
- Python 3.11+. Foundry agents use `azure-ai-projects>=2.5.0` (new Agents API):
  `AIProjectClient(...).agents.create_version(agent_name=..., definition=PromptAgentDefinition(...))`
  and run via `project.get_openai_client().responses.create(..., extra_body={"agent_reference": {"name": ..., "type": "agent_reference"}})`.
- Auth is always `DefaultAzureCredential` (no keys in code). APIM subscription keys come from `agents/procode/.env` or a Foundry project connection.
- The agent definition source of truth is `agents/procode/agent.yaml` + `instructions.md`. To change model/tools, edit the YAML, not the Python.
- APIM policies live in `apim/policies/*.xml`, one per governance layer (models, tools/MCP, agents/A2A). Never read `context.Response.Body` in MCP policies.
- Hosted agent lives in `agents/hosted/` (Microsoft Agent Framework: `Agent`, `FoundryChatClient`, `@tool`, `ResponsesHostServer`), deployed with `azd ai agent`.
- Infra: `infra/main.bicep` (new environment) or `infra/existing.bicep` + `infra/modules/` (existing Foundry/APIM). Keep both in sync when changing APIM config.
- APIM names are `whisker-` prefixed: backends `whisker-foundry-models`, `whisker-content-safety`; products `whisker-bronze`, `whisker-gold`; subscriptions `whisker-demo-bronze`, `whisker-demo-gold`. MCP path: `whisker-mcp`.
- Scripts read settings from `agents/procode/.env` (written by `scripts/deploy.sh`).
- Store API product IDs look like `WW-001`; order IDs like `ORD-1001`.
