<a id="09--apim-layer-2-mcp-governance-and-human-approval"></a>

<a id="11--apim-layer-2-mcp-governance-and-human-approval"></a>

# 11. Govern MCP tools

**Previous:** [10 — Content Safety](10-content-safety-gateway.md).
**Next:** [12 — A2A governance](12-govern-agent-to-agent-calls.md).

**Goal:** govern the working Store MCP server, expose an external MCP server, and optionally demonstrate
human approval for an order-writing tool. All steps for this segment are here; no jump to another topic is required.

**Starting point:** topic 3 created `whisker-mcp` and its Foundry connection; topic 4 created
`whiskers-concierge-pro`. Keep the working read-only server and connection intact.

## Part A — Govern an existing external MCP server

1. Azure portal > APIM > **MCP Servers**. If `learn-mcp` exists, inspect and reuse it.
2. Otherwise select **+ Create MCP server** > **Expose an existing MCP server**.
3. Base URL: `https://learn.microsoft.com/api/mcp`; transport: **Streamable HTTP**; name and base path:
   `learn-mcp`; products: Whisker Gold and Whisker Bronze.
4. In VS Code, open [.vscode/mcp.json](../.vscode/mcp.json), start `ms-learn-via-apim`, and supply the APIM
   hostname only and Gold key.
5. Ask *"What is APIM's llm-token-limit policy?"*. Verify the answer uses the Learn MCP tool rather than a
   direct web lookup. An external server is now behind your gateway's keys, limits, and logging.

### A separate Foundry agent for Learn MCP

Keep both concierge definitions unchanged. Create a custom MCP project connection named `whisker-learn`
with target `https://<apim>.azure-api.net/learn-mcp/mcp` and Gold key authentication in header
`Ocp-Apim-Subscription-Key`. Do not reuse the Store-targeted connection: Foundry can resolve its target
instead of the other endpoint specified on a tool, resulting in no matching Learn tools.

Create Professor Purr from its separate [Learn configuration](../agents/procode/learn-agent.yaml):

```bash
.venv/bin/python agents/procode/create_agent.py --config agents/procode/learn-agent.yaml
```

Ask `whisker-learn-guide` to search Microsoft Learn for APIM's `llm-token-limit` reference and fetch the page.
Verify actual `mcp_call` output for `microsoft_docs_search` and `microsoft_docs_fetch`, not just answer text.

The scripted APIM setup uses backend `whisker-learn-mcp`, base URL `https://learn.microsoft.com/api`,
and message endpoint `/mcp`. `serviceUrl` alone can create an empty REST-backed MCP server; putting
`/mcp` in both the backend URL and endpoint produces a duplicate path. Verify `tools/list` returns the
three Learn tools after setup.

### Repeatable read-only end-to-end validation

The [notebook walkthrough](whisker-works-demo-runbook.ipynb) includes creation and validation cells. From the
workspace root, the equivalent check is:

```bash
.venv/bin/python scripts/test-agent-mcp.py
# If the optional Orders MCP exists, include discovery only:
.venv/bin/python scripts/test-agent-mcp.py --orders-discovery
```

Both concierges must execute all five Store read tools; Professor Purr must execute Learn search, page
fetch, and code-sample search. Successful responses without real MCP calls fail. The checker validates
Store IDs/result shapes, reports versions and response IDs without credentials, exits nonzero on any
failed check, and never approves or places orders. It runs sequentially with 15-second pauses, 90-second
request timeouts and a 600-second request/retry budget. One retry is allowed for read-only throttled
requests; governance is not disabled. Use `--scope store` or `--scope learn` for targeted reruns, and
`--low-code-version`, `--pro-code-version`, `--learn-version` to pin saved numeric versions.
Orders discovery is not an execution or approval test.

## Part B — Apply MCP governance policies

1. In APIM, open `whisker-mcp` > **Policies** and apply
   [mcp-tools-policy.xml](../apim/policies/mcp-tools-policy.xml). Repeat on `learn-mcp`.
2. Inspect the controls:
   - **Who:** subscription keys and product membership.
   - **Which tools:** the server's **Tools** blade; use its actual discovered names, not REST operation IDs.
   - **How much:** `rate-limit-by-key`, normally 30 `tools/call` requests per 60 seconds, per MCP API and
     subscription (client IP when no subscription is available). Separate MCP servers do not share counters.
     Initialization, discovery, notifications and SSE connections do not consume this budget.
     APIM's distributed rate counters are approximate, not a strict transactional quota.
   - **Visibility:** `trace` records the subscription and `x-agent-id` if the client supplies it; otherwise the
     agent field is `unknown`.
3. If diagnostics are not enabled for the MCP API, enable Application Insights diagnostics with the existing
   `whisker-appinsights-logger`. Keep request and response payload bytes at **0**.
4. Never read `context.Response.Body` in MCP policies: it breaks streaming.

## Part C — Prove governance and restore the baseline

1. Temporarily set `calls="3"` on `whisker-mcp`. Start a new conversation and make enough MCP requests to
   receive **429**. Only `tools/call` consumes the budget; a prompt can make multiple tool calls, so four
   prompts are not an exact threshold. Malformed JSON is still subject to the limit before MCP validation.
2. Restore `calls="30"` and wait for the 60-second window to reset before proceeding.
3. Optionally remove the order-status tool (`getOrderStatus` on the portal-created server) in APIM.
   Start a new conversation or restart the MCP client to refresh discovery, then ask about an order.
   Verify that removing the tool changes discovery without changing the agent definition.
4. Re-add the same order-status operation and verify discovery and the `ORD-1002` query work again.
5. Inspect the gateway telemetry and Foundry tool spans. Do not rotate or suspend a shared Gold key as part of this test:
   that would also disconnect the other demo clients.

### Storefront throttling

Foundry can wrap an MCP HTTP 429 as a `400 tool_user_error`. The
[storefront chat endpoint](../src/catstore-api/main.py) recognizes this form and direct Foundry 429s,
returns HTTP 429 with `Retry-After`, and displays a friendly wait message rather than `BadRequestError`.
Other upstream failures remain HTTP 502 and are logged with their error type and request ID, not prompts or keys.
The widget allows only one pending request to keep conversation history ordered.
It does not automatically replay an agent response: an earlier tool call might already have placed an order.
The read-only comparison and smoke-test scripts keep their existing bounded retry behavior.

## Part D — Optional write server with human approval

Skip this part if you only want to demonstrate read-only governance. It is a complete additional demo, not a
required step for the earlier agent topics.

### 1. Create a separate Gold-only order server

1. APIM > **MCP Servers** > **+ Create MCP server** > **Expose an API as an MCP server**.
2. Choose **Whisker Works Store API** and select **only** the `placeOrder` REST operation.
3. Set name and base path to `whisker-mcp-orders`; display name: **Whisker Works Orders MCP**.
4. Attach **Whisker Gold only**, require a subscription, and create the server.
5. Apply the same MCP policy and zero-payload diagnostics from Part B.
6. Copy the endpoint: `https://<apim>.azure-api.net/whisker-mcp-orders/mcp`.
7. Inspect its **Tools** blade and record the actual order-tool name. The portal may derive a different MCP
   name from the operation's display name; do not assume it is `placeOrder`.

Do not add this tool to `whisker-mcp`. Product access restricts callers; human approval is a separate
**agent/client setting**, not an APIM policy or MCP-server property.

<a id="2-create-an-isolated-approval-demo-agent-in-foundry"></a>

### 2. Create an isolated approval-test agent in Foundry

1. Create a prompt agent named `whiskers-orders-approval` with model `gpt-4.1-mini`.
2. Paste these instructions:

   ```text
   You are Whiskers, the Whisker Works order assistant.
   Only place an order after the customer explicitly confirms product IDs, quantities, customer name,
   and shipping country. Never invent missing values. Summarize the order before requesting the tool.
   Use the order MCP tool for execution; do not claim success until its result confirms creation.
   If approval is denied, say that no order was placed.
   ```

3. Add a custom MCP tool with server label `whisker_orders` and the order-server endpoint above.
4. Use **Key-based** authentication with header `Ocp-Apim-Subscription-Key` and the Gold key.
   Create a separate project connection, for example `apim-whisker-mcp-orders`; leave the read-only connection unchanged.
5. Select **Always require approval** for this MCP tool and save the agent.

The SDK equivalent is `require_approval="always"` on `MCPTool`. In this kit's YAML-driven pro-code definition,
the equivalent setting is:

```yaml
mcp:
  enabled: true
  server_label: whisker_orders
  require_approval: always
```

**This snippet is explanatory, not an instruction to change the main agent.** `require_approval` does not route
to the order server: `create_agent.py` also reads `APIM_MCP_PATH` and `MCP_PROJECT_CONNECTION_NAME`.
If you build a separate pro-code order agent, use a separate YAML config/name, set the path to
`whisker-mcp-orders`, and use its separate connection. Never repoint the working concierge agent for this approval test.

<a id="3-show-denial-without-changing-inventory"></a>

### 3. Verify denial without changing inventory

From the workspace root:

```bash
source .venv/bin/activate
cd agents/procode
python chat.py --agent whiskers-orders-approval
```

1. Say *"I confirm: one WW-003 for Demo Cat, shipping country US. Please place the order."*
2. The client prints `approve whisker_orders.<discovered-tool-name>(...)? [y/N]`.
   Review the proposed product, quantity, name, and country.
3. Enter **n**. Confirm the agent reports the denial and does not claim an order was placed.
   The order tool must not execute; no stock should change.
4. Optionally repeat with **y** only if you intend to create a real order in the demo store.
   This decrements stock and creates an order; record the returned order ID. Do not approve solely to test connectivity.

Customer confirmation in the prompt and runtime tool approval are two distinct gates. The CLI handles
`mcp_approval_request` and submits the user's decision before execution.

### 4. Finish the segment

Exit the order-agent chat. Leave the main concierge agent, its read-only MCP path, and its connection unchanged.
Verify `whisker-mcp` still has five read-only tools and its normal 30-call limit.
Continue to [topic 12](12-govern-agent-to-agent-calls.md).

## Hardening notes

- Prefer Entra ID for production; product keys are used here for the demo.
- Use allow-lists on the agent and gateway, using names returned by `tools/list`.
- Treat tool output as untrusted. Validate any optional content-safety policy against your MCP request format
  before enabling it; do not assume model-oriented defaults understand every JSON-RPC payload.
- Host write tools separately with approval and narrow access; never rely on agent instructions alone.

## Docs

- [Expose a REST API as an MCP server](https://learn.microsoft.com/azure/api-management/export-rest-mcp-server)
- [Expose an existing MCP server](https://learn.microsoft.com/azure/api-management/expose-existing-mcp-server)
- [Secure MCP servers](https://learn.microsoft.com/azure/api-management/secure-mcp-servers)
- [Foundry MCP tools and approval](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/model-context-protocol)
- [Foundry MCP authentication](https://learn.microsoft.com/azure/foundry/agents/how-to/mcp-authentication)
