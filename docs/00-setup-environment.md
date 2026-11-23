# 00 — Set up the demo environment

> Already have a Foundry project and an APIM instance? Follow [00b-setup-existing-environment.md](00b-setup-existing-environment.md) instead.

## 1. Prerequisites

| Item | Notes |
|------|-------|
| Azure subscription | Owner (or Contributor + User Access Administrator) on the target resource group — the template creates role assignments. |
| Model quota | `GlobalStandard` quota for **gpt-4.1-mini** and **gpt-5-mini** in Southeast Asia (50K TPM each by default; lower `modelCapacity` if needed). Confirm that the selected model versions and APIM Basic v2 are currently available in Southeast Asia before deployment. |
| Region | Defaults to **Southeast Asia** (`southeastasia`) in the Bicep template and deploy script. Set `LOCATION=<azure-region>` to override. |
| Azure CLI ≥ 2.67 | `az bicep upgrade` |
| Python 3.11+ | For the scripts and pro-code agent |
| VS Code | Extensions in [.vscode/extensions.json](../.vscode/extensions.json) — Foundry Toolkit, GitHub Copilot + Chat, Bicep, Azure API Management, Python, REST Client |
| Git or GitHub Desktop | Clone the repository. A fork and configured GitHub Actions are needed only for the optional CI/CD workflow in topic 8. |
| Azure Developer CLI | `azd` + `azd ext install azure.ai.agents` — for the hosted agent demo (docs/05) |
| Docker (optional) | Needed for hosted-agent container builds/runs, not the remote code-deployment route (topic 5). |
| Optional | MCP Inspector (`npx @modelcontextprotocol/inspector`) |

<a id="2-get-the-repo-with-github-desktop"></a>

## 2. Get the code

Clone the repository into a local folder and open that folder in VS Code. Replace
`<repository-url>` with this repository's URL, or your fork's URL if you plan to push changes:

```bash
git clone <repository-url> whisker-works
cd whisker-works
code .
```

Alternatively, in **GitHub Desktop**, choose **File > Clone repository > URL**, enter the repository
URL, and use **Repository > Open in Visual Studio Code** after cloning. If you already have the
code locally, open the existing folder instead. Publishing a repository is not required to run the
agents or gateway checks. Use your own fork and configure GitHub Actions only if you choose the CI/CD exercise.

The commands in these guides use Bash and Python 3.11+ on Linux, macOS, or WSL. Run commands from the
repository root unless a step explicitly changes directory. Replace angle-bracket placeholders with your
own values; never copy credentials into source files or notebook cells.

## 3. Deploy Azure resources

```bash
az login
az account set --subscription "<your subscription>"
python3 -m venv .venv && source .venv/bin/activate
pip install -r agents/procode/requirements.txt
PUBLISHER_EMAIL=you@contoso.com RG=rg-whisker-works LOCATION=southeastasia ./scripts/deploy.sh
```

What it does:
The **optional** tags `CostControl=Ignore` and `SecurityControl=ignore` are enabled by default. Both Bicep templates
copy the demo resource group's tags onto all tag-capable resources they create. Child resources such as APIM operations,
model deployments and role assignments do not support independent tags. This is template-based propagation, not an Azure Policy
that tags resources created later by other tools. Only enable these exemption tags when your organization's governance permits them.

To deploy without adding the two control tags:
```bash
ENABLE_CONTROL_TAGS=false PUBLISHER_EMAIL=you@contoso.com ./scripts/deploy.sh
```
This skips adding the tags; it does not remove existing resource-group tags, which are still copied to deployed resources.

1. Deploys [infra/main.bicep](../infra/main.bicep):
   - Foundry account (`AIServices`) + project **whisker-works** + deployments **gpt-4.1-mini** and **gpt-5-mini**
   - APIM **Basic v2** (one unit) with system-assigned managed identity, App Insights logger, token metrics enabled
   - APIM backends `whisker-foundry-models` (with circuit breaker) and `whisker-content-safety`
   - APIM APIs: **Foundry Models (AI Gateway)** (`/models`) with [models-api-policy.xml](../apim/policies/models-api-policy.xml); **Whisker Works Store API** (`/store`) imported from [openapi.json](../src/catstore-api/openapi.json)
   - Products **Whisker Bronze** / **Whisker Gold**, subscriptions `whisker-demo-bronze`, `whisker-demo-gold`, `whisker-a2a-agent-internal`
   - App Service plan (B1) + 2 Python web apps (store + storefront, A2A agent); Log Analytics + Application Insights
   - Role assignments: APIM MI → *Cognitive Services OpenAI User* + *Cognitive Services User*; storefront MI and you → *Azure AI User*; you → *Foundry Project Manager* on the project (hosted agents)
2. Zip-deploys both web apps.
3. Writes `agents/procode/.env` (git-ignored) with endpoints and APIM keys.

### Cost and tier choice

Basic v2 is the cost-efficient default for this public-endpoint demo and supports its model, MCP tool and A2A governance scenarios.
Using the public Southeast Asia rates checked on 4 October 2026 and 730 hours/month, allow approximately **US$150/month for APIM**
and **US$13/month for the shared Linux B1 plan**, or **US$163/month fixed**, plus model tokens, monitoring, tools and optional hosted-agent resources.
Actual charges depend on your agreement, taxes and usage; see [APIM pricing](https://azure.microsoft.com/pricing/details/api-management/).

Basic v2 does not provide Standard v2's networking capabilities. This kit uses public endpoints; private-network scenarios need a separate design.
Existing-resource mode does not change the tier of your APIM instance. These edits change the template, not any already deployed service;
review the supported tier-change procedure before applying it to an existing Standard v2 instance.

## 4. Verify

```bash
source .venv/bin/activate
set -a; source agents/procode/.env; set +a
curl -s "$APIM_GATEWAY_URL/store/products?category=beds" -H "Ocp-Apim-Subscription-Key: $APIM_GOLD_KEY" | head -c 300; echo
python scripts/test-gateway.py basic
```

- Open the storefront URL printed by the script — you should see the product grid and a cat fact. (The chat widget works after step 6.)
- Open `https://<a2a-app>.azurewebsites.net/.well-known/agent-card.json` — you should see the agent card.

> First call to the web apps can take ~1 min (Oryx build + cold start).

## 5. Verify Application Insights tracing

The deployment creates `whisker-appi-xxxx`, connects it to the **whisker-works** project, and grants the project
identity the monitoring-reader roles required to display generative-AI trace content.

In the Foundry portal (<https://ai.azure.com>), open project **whisker-works** > **Operate / Monitoring**
(or **Agents > Traces**). Confirm the page names `whisker-appi-xxxx` and no longer shows the **Connect** banner.
If the banner remains immediately after deployment, refresh after role and resource propagation.

<a id="6-pre-create-the-demo-assets-recommended-before-presenting"></a>

## 6. Optional: prepare shared agents and traces

The numbered topics create their agents as you reach them; you do not need every agent in advance.
For a standalone storefront or terminal workflow, create the read-only Store MCP and the default
`whiskers-concierge-pro` with these commands after infrastructure verification:

```bash
# Create or reuse read-only MCP servers; do not delete an agent's active server
READ_ONLY=true ./scripts/create-mcp-servers.sh

# Pro-code agent v1 (gpt-4.1-mini) - also powers the storefront chat
cd agents/procode && python create_agent.py && cd ../..
```

If you also want the low-code exercises, build the agent in [topic 2](02-build-prompt-agent-foundry-portal.md).
Complete [its Store MCP connection in topic 3](03-connect-store-tools-mcp.md)
before seeding traces or running evaluations.

After both concierge agents exist, seed representative conversations and traces:

```bash
source .venv/bin/activate
python scripts/seed-agent-traces.py
```

This seeds the low-code agent used in topic 7. To seed both agents after the pro-code agent exists, pass
`--agents whiskers-concierge whiskers-concierge-pro`. Allow several minutes for Application Insights ingestion,
then follow [topic 7](07-versions-traces-evaluations.md).

Deploy the hosted agent only if you choose [topic 5](05-build-hosted-agent-framework.md).
That guide covers initialization, deployment, and optional local debugging.

## 7. Import the A2A agent into APIM

If you choose the A2A exercise, follow the complete import and policy steps in
[topic 12](12-govern-agent-to-agent-calls.md#steps). Use base path `wellness-agent`.

## 8. Clean up

```bash
RG=rg-whisker-works ./scripts/cleanup.sh
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `InsufficientQuota` on deployment | Lower `modelCapacity`, change region, or switch model versions. |
| `401` from `/models` | Role assignment propagation — wait a few minutes. |
| `403` from `/models` on a benign prompt | Content safety thresholds — raise them in the policy. |
| MCP client hangs | Ensure global APIM diagnostics log **0** response body bytes (template does this). Don't read `context.Response.Body` in MCP policies. |
| Storefront chat `503` | Agent `whiskers-concierge-pro` not created yet (step 6). |
| `PermissionDenied` creating agents | You need **Azure AI User** on the Foundry account (template assigns it to the deploying user). |
| `azd deploy` of the hosted agent fails with authorization errors | You need **Foundry Project Manager** on the project (template assigns it); re-run `az login` / `azd auth login` after role propagation. |
