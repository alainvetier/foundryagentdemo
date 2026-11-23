<a id="11b---optional-your-runtime-foundry-observability-apim-controls"></a>

<a id="06---optional-your-runtime-foundry-observability-apim-controls"></a>

# 6. Optional: Run the agent application on Container Apps

**Previous:** [05 - Foundry-hosted Kernel Panic](05-build-hosted-agent-framework.md).
**Next:** [07 - Agent details and evaluation](07-versions-traces-evaluations.md).

> Container Apps runs our code. Foundry observes and evaluates it.
> APIM enforces controls on requests routed through the gateway.

Kernel Panic now has a second, deliberately **read-only** incarnation:
`kernel-panic-aca`. It shares the sales calculations and CSV with the hosted
agent, but runs its own small model/tool loop using the Responses API.
It is not a second Foundry-managed hosted deployment. The existing
`kernel-panic-ops` deployment is unchanged.

<a id="what-the-audience-should-understand"></a>

## Compare the runtime options

| | Topic 5: hosted | Optional topic 6: external |
|---|---|---|
| Application runs on | Foundry-managed runtime | Azure Container Apps |
| Deployment and scaling | Foundry hosting | Your Container Apps configuration |
| Agent loop | Agent Framework application | Standalone application using Responses |
| Foundry registration | Hosted agent version | External-agent telemetry registration (preview) |
| Invocation | Foundry Playground / agent endpoint | Separate client through APIM |
| Observability | Foundry-hosted runtime integration | Explicit OpenTelemetry export and matching agent ID |
| Store-tool enforcement | APIM MCP policies | The same APIM MCP policies |
| Additional inbound controls | Depends on the invocation path | Dedicated APIM API, subscription, action gate and rate limit |
| Purchase orders | Approval-gated simulated tool | Not exposed at all |

External-agent registration is **preview**, not an enforcement mechanism.
It does not host, proxy or invoke this app, and does not give it the hosted-agent
Playground or runtime conversation/approval handling. Do not describe registration
as automatically applying Foundry guardrails or giving hosted-feature parity.

```mermaid
flowchart LR
    Demo[Notebook / test client] --> Gateway[APIM whisker-ops]
    Gateway -->|Managed identity / Entra token| ACA[Kernel Panic on Container Apps]
    ACA --> Model[Existing Foundry model]
    ACA --> MCP[APIM whisker-mcp]
    MCP --> Store[Read-only Store inventory]
    ACA -. OpenTelemetry .-> Insights[Linked Application Insights]
    Insights -. Matching gen_ai.agent.id .-> Foundry[Foundry external agent traces]
```

The model is called directly with the Container App's managed identity:
this demo does **not** claim APIM model policies apply to that direct path.
APIM policies apply to inbound agent calls and MCP traffic. The Store backend's
existing direct access posture is not hardened by this optional deployment.

<a id="prepare-before-the-session"></a>

## Set up the optional runtime

Prerequisites:
- Infrastructure setup and [Store MCP setup](03-connect-store-tools-mcp.md) are complete,
  including the Foundry/Application Insights connection. Deploying the topic 5 hosted agent is not required.
- Azure CLI, working Azure credentials, and the repository Python environment.
- Permission to create Container Apps, a Basic container registry, a user-assigned
  identity, scoped role assignments, an Entra API app/service principal, and a
  dedicated APIM API/product association.
- Read access to linked monitoring resources for telemetry verification.

From the repository root:

```bash
.venv/bin/python -m pip install -r agents/container-app/requirements.txt
.venv/bin/python scripts/deploy-external-agent.py --deploy
.venv/bin/python scripts/test-external-agent.py --verify-telemetry
```

The script uses the subscription and gateway settings from
`agents/procode/.env` (see the [settings template](../agents/procode/.env.sample)), discovers the existing Foundry
account and linked Application Insights, and uses the same additive
[Bicep template](../infra/external-agent.bicep) for NEW and EXISTING environments.
It does not redeploy either base environment or change global APIM policies.
Do not use the CLI's unrelated default subscription.

Deployment creates `whisker-ops-*` Container Apps resources, `whiskeraca*` ACR,
and an Entra application named `<apim-name>-kernel-panic-aca`. It builds only
allowlisted application files; credentials and notebook outputs are excluded
from the build context. APIM's identity obtains the backend Entra token without
a client secret. ACA authentication accepts only the configured APIM principal.
The app's own managed identity accesses the Foundry model and pulls its image.
Only the existing APIM Gold key is stored as an ACA secret for Store MCP calls.

A single 0.5-vCPU / 1-GiB replica stays warm to avoid cold-start surprises; this
and Basic ACR incur additional costs. Do not describe this as a free deployment.
The app is stateless: each request starts a new conversation and has at most
four model/tool rounds. It has no purchase-order or inventory-write function.

Non-secret deployment references are saved in `.build/external-agent.json`.
Never display the full ACA configuration or Foundry hosted-agent definition:
those can include settings or credentials unrelated to this demonstration.

<a id="live-walkthrough"></a>

## Verify the runtime and gateway

<a id="1-show-where-the-code-runs"></a>

### 1. Inspect where the code runs

Open the Container App printed by the deployment. Inspect the image revision,
single warm replica and managed identity. Contrast this with Topic 5's
Foundry-managed hosted runtime.

### 2. Run the optional notebook cell

The cell runs [test-external-agent.py](../scripts/test-external-agent.py).
It performs these checks without placing or approving any order:

1. Read back the Foundry registration: kind `external`, OpenTelemetry ID
   `kernel-panic-aca`.
2. Call ACA directly without a token: **401** from backend authentication.
3. Call APIM without a subscription: **401**.
4. Send `x-whisker-action: write` through APIM: **403**, explicitly marked
   `enforced_by: apim`. This is a declared action gate, not a classifier of
   arbitrary natural-language intentions. No request is forwarded to the model.
5. Send the valid read-only prompt:

   > Summarize September 2026 sales by category using sales_summary, then use
   > check_stock to check current stock of WW-004. Make both actual tool calls.
   > Do not place an order.

The successful response includes the answer, actual tool-call arguments/results,
response ID and trace ID. The test rejects answers that only claim tool execution.
It checks the actual MCP inventory result shape without assuming stock must stay
at a particular quantity.

The API also has a **10 requests/minute/subscription** rate limit, isolated from
the other demo APIs. Avoid repeatedly running the entire check within one minute.
Store MCP retains its own independent 30-call/minute limit.

<a id="3-show-observability-in-foundry"></a>

### 3. Verify observability in Foundry

Open the existing Foundry project's **Agents** list and select
`kernel-panic-aca`, then its trace experience. Find the trace ID printed by the
test. Inspect `invoke_agent`, model `chat`, `sales_summary`, and `check_stock` spans.
Each explicit span carries `gen_ai.agent.id=kernel-panic-aca`, matching the
external registration. Application Insights contains the underlying telemetry.

The telemetry check waits up to ten minutes for ingestion and requires the actual
correlated invocation, model and both tool spans, plus the ACA request and APIM
MCP/Store requests. It inspects **all** correlated requests, dependencies and
exceptions, including gateway items without `gen_ai.agent.id`. Any failed item
or exception fails the check. It requires two consecutive complete snapshots
with unchanged item IDs before reporting success, to allow for delayed gateway
ingestion. This is an ingestion-time check, not a guarantee against later arrivals.
A registration alone, a local export success, or unrelated older traces is not
proof of working observability. Continue only after verifying the correlated trace or
resolving the explicit telemetry error.

The app records synthetic demo prompt/answer content for trace inspection and
trace-based evaluation. Do not submit customer-sensitive information. Registration
makes the agent eligible for supported external-agent evaluation experiences;
this walkthrough does not automatically run or claim a passing evaluation.

<a id="4-show-the-control-boundary"></a>

### 4. Inspect the control boundary

Open APIM's `whisker-ops-aca` API policy. Locate subscription enforcement, the
read-only action gate, rate limiting, and managed-identity backend authentication.
Then inspect the existing MCP policy and the `kernel-panic-aca` caller identity.

> A trace tells us what happened. A policy decides what is allowed to happen.
> Registering an external agent connects observability, not enforcement.

## Troubleshooting

- **403 on the backend:** confirm ACA's allowed principal is the APIM managed
  identity, its allowed application is that identity's client ID, and the API
  audience matches its Entra application. To reapply infrastructure without
  rebuilding, use `deploy-external-agent.py --deploy --image-tag <existing-tag>`
  with the immutable tag recorded in `.build/external-agent.json`.
- **APIM 500 when acquiring a token:** allow the new Entra resource/service
  principal to propagate, then retry a read-only health request.
- **502 from the agent:** use its trace ID and ACA logs. Missing tool data or
  model permission errors are failures, not successful fallback answers.
- **Registration missing:** rerun `deploy-external-agent.py --register-only`;
  it refuses to replace a hosted/prompt agent with the same name.
- **No telemetry:** check the linked App Insights connection and telemetry ID.
  Telemetry verification fails explicitly on timeout.
- **Foundry says Failed but the agent returned HTTP 200:** inspect the entire
  trace, not just agent-tagged spans. APIM synthesized-MCP telemetry can contain
  `forward-request` dependencies with `success=false`, no result code, and target
  `forward-request` (data `REQUEST -`) even when agent/model/tool spans and MCP/Store
  HTTP requests succeeded. The checker deliberately reports such dependencies as failures;
  a successful answer alone does not establish a clean end-to-end trace.
  Preserve the full operation ID and correlated requests, dependencies, and exceptions
  when escalating the discrepancy to Azure support. Do not remove the MCP backend's
  `<base />` / inherited `forward-request`: doing so can prevent MCP dispatch and cause
  gateway timeouts. Do not drop failed dependencies, relabel them as successful, or disable
  gateway logging to make the trace green. Resolve or document the platform telemetry
  discrepancy separately from application success.

  To inspect a historical operation, use an explicit CLI time range as well
  as the operation ID (the CLI's default range can exclude older traces):

  ```bash
  az monitor app-insights query --subscription <demo-subscription> \
    --app <app-insights-app-id> --offset 7d \
    --analytics-query "union requests, dependencies, exceptions
  | where operation_Id == '<trace-id>'
  | project timestamp, itemType, name, success, resultCode, outerMessage, customDimensions
  | order by timestamp asc"
  ```

## Targeted cleanup

Do not run the base demo's resource-group cleanup for this optional topic.
After reviewing `.build/external-agent.json`, remove only the optional Container
App, its environment, dedicated registry, user-assigned identity, new APIM
`whisker-ops-aca` API, external `kernel-panic-aca` registration and dedicated Entra
application/service principal. Remove the identity's Foundry role assignments
as well. Preserve the shared Foundry project, model, monitoring, Store MCP, APIM
products/subscriptions, and the `kernel-panic-ops` hosted agent.

## References

- [Register external agents (preview)](https://learn.microsoft.com/azure/foundry/agents/how-to/register-external-agent)
- [Container Apps authentication](https://learn.microsoft.com/azure/container-apps/authentication)
- [APIM managed-identity authentication](https://learn.microsoft.com/azure/api-management/authentication-managed-identity-policy)
