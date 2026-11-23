<a id="11--hosted-agents-in-foundry-with-microsoft-agent-framework"></a>

<a id="05--hosted-agents-in-foundry-with-microsoft-agent-framework"></a>

# 5. Build a hosted agent with Agent Framework

**Previous:** [04 — Create the pro-code agent](04-create-prompt-agent-code.md).
**Next:** [06 — Optional Container Apps runtime](06-optional-container-apps-agent.md),
or skip to [07 — Agent details and evaluation](07-versions-traces-evaluations.md).
The optional runtime compares your own runtime with Foundry observability and explicit APIM controls.

**Story:** *Whiskers* (prompt agent) serves customers. Store staff need an **ops analyst** with custom logic:
Python tools that crunch sales data, a purchase-order action that needs human approval, and the governed Store
tools. Meet **Kernel Panic** 🐈‍⬛, Head of DevOps — a **hosted agent** written with **Microsoft Agent Framework**
and run by Foundry Agent Service.

## Prompt agents vs hosted agents

| | Prompt agent (demos 2, 4) | Hosted agent (this demo) |
|---|---|---|
| Definition | Model + instructions + tools (declarative) | **Your code** in a container (Agent Framework, LangGraph, any framework) |
| Orchestration | Foundry runtime | Your code (single agent, workflows, multi-agent) |
| Custom tools | OpenAPI / MCP / built-ins | **Plain Python functions** + MCP + Foundry tools |
| Run where | Foundry | Foundry-managed compute; **same local experience** with `azd ai agent run` |
| Protocol | Responses API | Responses (or Invocations) protocol via the hosting library |
| Governance | Versions, tracing, evals, identity | Same: versions, tracing, evals, **per-agent managed identity** |

## The code — [agents/hosted/](../agents/hosted/)

| File | Purpose |
|------|---------|
| [main.py](../agents/hosted/main.py) | Agent Framework `Agent` + `FoundryChatClient`, served by `ResponsesHostServer` |
| [agent.yaml](../agents/hosted/agent.yaml) | Hosted agent definition (`kind: hosted`, protocol, CPU/memory, env vars) |
| [agent.manifest.yaml](../agents/hosted/agent.manifest.yaml) | Template used by `azd ai agent init` (model resource + parameters) |
| [Dockerfile](../agents/hosted/Dockerfile) | Container image (port 8088) |
| `data/whisker-sales-2026.csv` | Copy of the sales data, packaged with the agent |

Read `main.py` and identify these implementation steps:
1. `@tool(approval_mode="never_require") sales_summary(...)` — a normal Python function becomes a tool (type hints + `Field` descriptions = tool schema).
2. `@tool(approval_mode="always_require") create_purchase_order(...)` — side effect → **human-in-the-loop**.
3. `client.get_mcp_tool(...)` — the **APIM MCP server** (`/whisker-mcp/mcp`) with header `x-agent-id: kernel-panic-hosted`, so the agent shows up in the APIM Layer 2 trace.
4. `ManagedIdentityCredential` when hosted, `AzureCliCredential` locally — no keys for Foundry.
5. `ResponsesHostServer(agent=create_agent, ...)` — the hosting library provides the HTTP server, health checks and the Responses protocol.

## Steps

### 0. Prerequisites
- Azure Developer CLI (`azd`) ≥ 1.20 and the agents extension:
  ```bash
  azd ext install azure.ai.agents
  azd auth login
  ```
- Docker running for container builds / local container runs. The code-deployment
  route below uses Foundry's remote build instead and does not need Docker or ACR.
- Role **Foundry Project Manager** on the project (the Bicep assigns it to the deploying user).
- Complete infrastructure setup and [topic 3](03-connect-store-tools-mcp.md) so APIM `/whisker-mcp` exists.
  The deployed agent can omit Store tools when APIM settings are absent, but the Store-tool checks in this
  guide require those settings. The local F5 launcher explicitly rejects missing gateway settings.

### 1. Initialize from the local manifest
For code deployment into your existing demo project, run this from the repository root.
Use the **demo subscription** and project ARM ID, not an unrelated CLI default:

```bash
mkdir -p ~/whisker-hosted
cd ~/whisker-hosted
azd ai agent init -m /path/to/repo/agents/hosted/agent.manifest.yaml \
  --agent-name kernel-panic-ops \
  --project-id "/subscriptions/<demo-subscription>/resourceGroups/<foundry-rg>/providers/Microsoft.CognitiveServices/accounts/<foundry-account>/projects/whisker-works" \
  --model-deployment gpt-4.1-mini \
  --deploy-mode code --runtime python_3_13 --entry-point main.py \
  --environment whisker-hosted --no-prompt
cd kernel-panic-ops
```

Initialization creates a **nested** `kernel-panic-ops` project directory containing
`azure.yaml`. Run subsequent azd commands there. It copies the local agent source,
including the sales CSV; re-copy changed source before redeploying if you later edit
the original [hosted agent](../agents/hosted/).

For the interactive/container alternative:

```bash
mkdir -p ~/whisker-hosted && cd ~/whisker-hosted
azd ai agent init -m /path/to/repo/agents/hosted/agent.manifest.yaml
cd kernel-panic-ops
```
Prompts: agent name `kernel-panic-ops` → **Use an existing Foundry project** → `whisker-works` → model deployment
**gpt-4.1-mini**. (Add `--deploy-mode code` to deploy as code instead of a container image if you prefer.)

Set the APIM values securely from your generated `agents/procode/.env`
(see the [settings template](../agents/procode/.env.sample) for variable names).
From the initialized project directory, use the repository's Python environment
(replace `/path/to/repo` in both places):

```bash
/path/to/repo/.venv/bin/python - <<'PY'
import subprocess
from dotenv import dotenv_values

settings = dotenv_values("/path/to/repo/agents/procode/.env")
values = {
    "APIM_GATEWAY_URL": settings["APIM_GATEWAY_URL"],
    "APIM_SUBSCRIPTION_KEY": settings["APIM_GOLD_KEY"],
    "AZURE_AI_PROJECT_ENDPOINT": settings["FOUNDRY_PROJECT_ENDPOINT"],
}
for name, value in values.items():
    if not value:
        raise ValueError(f"Missing setting: {name}")
    subprocess.run(["azd", "env", "set", name, value], check=True, capture_output=True, text=True)
print("Hosted-agent gateway settings configured (credentials not displayed).")
PY
```

Do not print the full `azd env get-values` or `azd ai agent show` JSON; both can
contain subscription keys. Keep the generated `.azure/` directory out of Git.

### 2. Provision (only creates what's missing, e.g. container registry)
**Skip this for code deployment into the existing project.** No new registry or
supporting infrastructure is needed. For container deployment with missing infrastructure:
```bash
azd provision
```

### 3. Run and test locally — the "inner loop"
This is an optional local development path, not a prerequisite for the deployed agent.
The repository now includes a local-only F5 configuration; no azd initialization, Docker,
deployment, or cloud-agent update is needed for this route.

#### What Inspector does

Inspector is a chat/test client for a **running local agent server**. It sends a request
to Kernel Panic at `http://localhost:8088` and displays the response and tool events.
It is not the Foundry portal and does not create or deploy an agent.

The Python debugger is separate: F5 starts this repository's server under `debugpy`;
a breakpoint pauses your Python tool while Inspector waits for the response.
The local server still calls the existing cloud model and APIM MCP endpoint.
It is not an offline/mock agent, and model/tool usage may incur charges.

#### One-time local setup

From the repository root, with the Python, Python Debugger, and Foundry Toolkit extensions
installed in the same VS Code environment as the workspace:

```bash
python3 -m venv agents/hosted/.venv
agents/hosted/.venv/bin/python -m pip install -r agents/hosted/requirements-dev.txt
agents/hosted/.venv/bin/python scripts/run-hosted-local.py --check
```

The environment is separate from the notebook's root `.venv`. Local development
requirements pin the API generation used by the existing source. Use these tested dependencies
instead of upgrading them independently. The production requirements are unchanged.

[run-hosted-local.py](../scripts/run-hosted-local.py) reads the existing ignored
`agents/procode/.env` each time (see the [settings template](../agents/procode/.env.sample)):
`CHAT_MODEL` supplies the model,
`APIM_GOLD_KEY` supplies the MCP subscription key, and the existing Foundry endpoint,
gateway URL, and MCP path are reused. It does not write settings, print credentials,
change the active Python interpreter, or touch the deployed `kernel-panic-ops`.
Local Responses history is kept under ignored `.build/agent-inspector/`.
Missing required settings produce an explicit error instead of silently omitting Store tools.

The existing local agent uses Azure CLI authentication. If `az account show` reports
that you are not signed in, run `az login` yourself against the demo tenant/subscription.
Toolkit's Azure sign-in and the CLI's sign-in are separate.

<a id="rehearse-f5-connect-send-inspect"></a>

#### Debug locally: start, connect, send, inspect

1. Stop any previous local agent on port 8088. Do not run `azd ai agent run` alongside F5.
2. Open [main.py](../agents/hosted/main.py). In `sales_summary`, click the gutter beside
   `return summarize_sales(group_by, month)` to set a breakpoint. This F5 route uses
   the **repository source**, not the copied source under `~/whisker-hosted/`.
3. Open **Run and Debug**, select **Whisker Works: Debug Kernel Panic locally**, and
   press **F5**. The configuration is in the workspace-root
   [launch.json](../.vscode/launch.json); it explicitly uses `agents/hosted/.venv/bin/python`.
4. Wait for the terminal to show the server running on `127.0.0.1:8088`.
   Do not expand environment variables or credential/client objects on screen.
5. Open **Foundry Toolkit > Developer Tools > Build > Agent Inspector**.
   Alternatively, run **Tasks: Run Task > Whisker Works: Open Agent Inspector** from
   the Command Palette; [tasks.json](../.vscode/tasks.json) opens the same built-in view.
   Opening the view does not start another server.
6. If needed, use the pencil beside the endpoint to set `http://localhost:8088`.
   Wait for **Connected**. Use **New chat** for a clean test.
7. Send this read-only prompt:

   > Summarize September 2026 sales by category using sales_summary. Do not place an order.

8. VS Code should pause at the breakpoint. In **Variables > Locals**, inspect
   `group_by = "category"` and `month = "2026-09"`.
   The model selected a tool and execution has entered the Python function.
   Inspector waiting while Python is paused is expected, not a failure.
9. Press **F5 / Continue**. In Inspector, inspect the `sales_summary` call,
   its arguments/result, and the final answer where available. In a normal fresh run,
   September Food revenue is **$13,977.30** and Toys revenue is **$6,396.80**.
   These are calculated from the packaged CSV, not invented by the model.
10. Remove/disable the breakpoint before continuing with other requests.
    Press **Shift+F5** to stop your local server when finished. Do not terminate unrelated tasks.

Inspector does not necessarily expose a full workflow graph, model reasoning, or every token/latency field.
The available views depend on events and instrumentation supplied by the server.

<a id="what-to-show-on-stage-two-minutes"></a>

#### Compare local and deployed execution

The sales-only Inspector prompt isolates local Python calculations. It does not prove that
the Store MCP gateway was called. To check the governed tool path, deploy the agent using
step 4, then use the Foundry Playground restock prompt below and **deny** the purchase-order
approval. Inspect the Store-tool calls and traces separately from the local sales result.

#### Troubleshooting and fallback

| Symptom | Action |
|---|---|
| F5 configuration is missing | Open the repository root as the VS Code workspace, then select the named launch configuration. |
| Missing interpreter/module or SDK import error | Rerun the local setup with `requirements-dev.txt`; do not install into the notebook environment. |
| Port 8088 is in use | Stop your previous debug/local-run session; do not kill an unrelated process or start a second server. |
| Inspector is disconnected | Wait for server startup, confirm `http://localhost:8088`, then reconnect. `http://localhost:8088/readiness` should return HTTP 200; `/` can return 404 normally. |
| Response appears stuck | Check whether VS Code is paused at your breakpoint; press Continue. |
| Breakpoint is hollow or never hit | Use the repository's `main.py`, confirm this launch configuration is running, and request `sales_summary` explicitly. |
| CLI login or service error | Resolve the explicit terminal error before retrying; a Toolkit login alone does not authenticate the CLI. |
| Remote SSH/WSL workspace | Install Toolkit and Python debugging support on the workspace side. Keep any VS Code forwarding of 8088 private; never publish the unauthenticated local server. |

If Inspector is unavailable, you can still test the agent after step 4 using the notebook invocation
or deployed Playground. The alternative initialized-project
route still works: run `azd ai agent run --no-client` in its `azure.yaml` directory and,
in another terminal there, `azd ai agent invoke --local "Which category grew the most
between April and September?"`. That route runs its copied source and does not use this
repository's F5 launch configuration.

Prompts to try:
- *"Which category grew the most between April and September?"* → `sales_summary(group_by="month")` / `category`
- *"Is the Premium Cardboard Box in stock? If not, restock it."* → MCP `checkStockLevel` (or your server's discovered
  inventory tool name; see the [mapping](03-connect-store-tools-mcp.md#confirm-the-exposed-tool-names))
  → proposes `create_purchase_order` → **approval request**
- *"Compare Keyboard Warmer Nap Pad sales in June vs September and explain the trend."*

### 4. Deploy to Foundry Agent Service
```bash
azd deploy
```
The output shows the **agent playground** link and the agent endpoint. Then:
```bash
azd ai agent invoke "Give me a 3-bullet ops summary for September."
```

In the [runbook](whisker-works-demo-runbook.ipynb), run Topic 5's **hosted-agent
prerequisites** cell before the invocation cell. Its default project directory is
`~/whisker-hosted/kernel-panic-ops`; override it with `WHISKER_HOSTED_PROJECT` if
needed. It checks that Kernel Panic is active and has the model and APIM settings,
and prints only a credential-free readiness summary. It does not provision,
deploy, or invoke the model. The invocation cell still requires explicit approval.

<a id="5-show-it-in-foundry"></a>

### 5. Inspect it in Foundry
- **Agents** list: `kernel-panic-ops` next to `whiskers-concierge` and `whiskers-concierge-pro` — prompt and hosted agents side by side.
- **Playground**: ask the restock question and **deny** the purchase-order request to verify approval without changing data.
- **Versions**: each `azd deploy` = new version. **Traces**: spans for the model calls, local tools and the MCP calls.
- **APIM**: App Insights / Test trace shows `MCP call | agent=kernel-panic-hosted` from [mcp-tools-policy.xml](../apim/policies/mcp-tools-policy.xml).

<a id="seven-minute-presentation-path"></a>

### Verify the deployed approval boundary
1. Open the deployed `kernel-panic-ops` in the Foundry Playground.
2. Ask whether the Premium Cardboard Box is in stock and request a restock if it is not.
3. Inspect the read-only inventory tool result and the proposed purchase-order arguments.
4. **Deny** the purchase-order approval. Confirm that no order was placed.
5. Inspect the tool and trace evidence and locate the Store MCP request in APIM telemetry.

You can use Inspector, the notebook, and the Playground independently. Local success does not prove
deployed identity, configuration, or network access: the Playground exercises the deployed runtime.
Continue to [topic 7](07-versions-traces-evaluations.md) for evaluation and trace analysis.

<a id="6-iterate-optional-ties-into-demo-6"></a>

<a id="6-iterate-optional-ties-into-demo-8"></a>

### 6. Iterate (optional)
- Change instructions or add a tool in `main.py` with Copilot (*"Add a tool that returns the top 3 products by return rate"*), `azd ai agent run` to test, `azd deploy` → new version.
- Switch the model: `azd env set AZURE_AI_MODEL_DEPLOYMENT_NAME gpt-5-mini` → `azd deploy`.

<a id="talking-points"></a>

## What to verify
- **Same platform, two styles:** declarative prompt agents for speed, hosted agents when you need code — both get versions, identity, tracing, evaluation.
- **Any framework**: Agent Framework here, but LangGraph, OpenAI Agents SDK, GitHub Copilot SDK also run as hosted agents.
- **Governance still applies:** the hosted agent's tool traffic goes through the APIM MCP server (rate limits, keys, tool selection) like every other agent.

## Docs
- [Develop agents with Agent Inspector in Foundry Toolkit](https://code.visualstudio.com/docs/intelligentapps/agent-inspector)
- [Quickstart: deploy your first hosted agent](https://learn.microsoft.com/azure/foundry/agents/quickstarts/quickstart-hosted-agent)
- [Quickstart: deploy your own code as a hosted agent](https://learn.microsoft.com/azure/foundry/agents/quickstarts/quickstart-deploy-own-code)
- [Host Microsoft Agent Framework agents as Foundry hosted agents](https://learn.microsoft.com/azure/foundry/how-to/develop/framework-hosted-agents)
- [Deploy a hosted agent (permissions)](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent)
- [Hosted agent permissions reference](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agent-permissions)
- [Agent Framework: Foundry hosted agents](https://learn.microsoft.com/agent-framework/hosting/foundry-hosted-agent)
- [Agent Framework hosted samples (Python)](https://github.com/microsoft/agent-framework/tree/main/python/samples/04-hosting/foundry-hosted-agents/responses)
- [Foundry samples: hosted agents](https://github.com/microsoft-foundry/foundry-samples/tree/main/samples/python/hosted-agents)
