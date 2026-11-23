<a id="03--create-the-store-mcp-server-and-connect-whiskers"></a>

# 3. Connect store tools with MCP

**Goal:** expose the Store REST API as five read-only MCP tools, test them in VS Code, and connect the low-code
agent. Finish this entire guide before creating the pro-code agent in topic 4.

**Starting point:** infrastructure is deployed and `whiskers-concierge` exists from topic 2.
The Store API is imported into APIM, but its MCP server is not created by the infrastructure deployment.
If `whisker-mcp` already exists from a previous run, inspect and test it instead of deleting or recreating it.

<a id="part-a--expose-a-rest-api-as-an-mcp-server-the-easy-demo"></a>

## Part A — Expose a REST API as an MCP server

1. Azure portal > APIM > **APIs** > *Whisker Works Store API* — inspect its 6 REST operations.
2. **APIs** > **MCP Servers** > **+ Create MCP server** > **Expose an API as an MCP server**.
3. **API**: *Whisker Works Store API*. **Operations**: select all **except** `placeOrder`
   ("start read-only — least privilege for agents").
4. **Display name** `Whisker Works MCP`, **Name** `whisker-mcp`, description *Store tools for AI agents*.
5. **Products**: *Whisker Gold* and *Whisker Bronze*. **Create**.
6. Copy the **Server URL** from the MCP Servers list. That's it — no code, no redeploy of the backend.

### Confirm the exposed tool names

Use the MCP client's discovered tool list (`tools/list`) or APIM's **Tools** blade to confirm the exact names.
MCP tool names can differ from the REST API operation IDs, depending on how the server was created.
The portal-created server used for validation returned these names:

| MCP tool name | REST operation ID | Purpose |
|---|---|---|
| `listOrSearchProducts` | `listProducts` | List products; optionally filter by `category` or `q` |
| `getAProduct` | `getProduct` | Get details using `productId` |
| `checkStockLevel` | `checkInventory` | Check inventory using `productId` |
| `getOrderStatus` | `getOrder` | Look up an order using `orderId` |
| `getARandomCatFact` | `getRandomCatFact` | Return a cat fact |

The backup script uses REST operation IDs as tool names, so a script-created server can expose the names in the
second column instead. Use the discovered names for direct tool calls, agent allow-lists, and governance changes;
do not assume either naming scheme. `placeOrder` is intentionally excluded from the read-only setup.

For the backup script, set `AZURE_SUBSCRIPTION_ID` in the ignored `agents/procode/.env` to the subscription
containing APIM. New deployments record it automatically. The script prints and checks its APIM target before
making changes and uses that subscription explicitly; older settings without it use the Azure CLI default.
If `ResourceGroupNotFound` appears even though the group exists in the portal, compare the portal's subscription
ID with this setting, and verify `APIM_RG` and `APIM_NAME`. No global CLI subscription change is required.

For the Learn passthrough payload, `mcpProperties.endpoints` is a named object:
`{"message":{"uriTemplate":"/mcp"}}`. An endpoint array can fail with a dictionary-deserialization
`ValidationError` on the deployed APIM service. After correcting that payload, rerun the backup script
to finish the Learn policy and product associations; the earlier Store MCP changes may already have succeeded.

### Test it from VS Code (GitHub Copilot as MCP client)
1. Open [.vscode/mcp.json](../.vscode/mcp.json) > **Start** above `whisker-works-via-apim` > enter the APIM
   **hostname only**, for example `whisker-apim-abc123.azure-api.net`, and the Gold key.
   Do not paste `https://`, `/whisker-mcp/mcp`, or a trailing slash: the configuration adds those itself.
2. Copilot Chat > **Agent** mode > **Tools** — the 5 store tools appear.
3. Ask: *"Which beds are in stock under $60? Also give me a cat fact."* → on the portal-created demo server,
   Copilot calls `listOrSearchProducts`, `checkStockLevel`, and `getARandomCatFact` through APIM.
   Verify the calls in the tool output; names can differ on a script-created server.

Alternative client: `npx @modelcontextprotocol/inspector` → Streamable HTTP, URL above, header `Ocp-Apim-Subscription-Key`.

If the MCP output shows `https://https://...` and `getaddrinfo ENOTFOUND https`, the saved hostname contains a URL
scheme. Stop the server, run **MCP: Reset Cached Inputs** from the VS Code Command Palette, and start it again
with the hostname only. This error occurs before the request reaches APIM; changing keys or gateway policies
will not fix it.

## Part B — Connect the low-code agent

1. In Foundry, open **whisker-works** > **Agents** > `whiskers-concierge`.
2. **Tools** > **Add** > **Custom** > **Model Context Protocol (MCP)**.
3. Name the tool `whisker_store`. Set the endpoint to `https://<apim>.azure-api.net/whisker-mcp/mcp`.
4. Choose **Key-based** authentication, header `Ocp-Apim-Subscription-Key`, and the Gold key.
   Name the resulting project connection `apim-whisker-mcp` if the dialog allows it; otherwise note its actual
   connection name/ID for Part C.
5. Select **Never require approval** for these read-only tools. The separate write-tool approval demo is in
   [topic 11](11-govern-mcp-tools.md#part-d--optional-write-server-with-human-approval), not a prerequisite here.
6. Save a new version and start a new Playground conversation.
7. Ask *"Is the Premium Cardboard Box in stock?"* and *"What's the status of order ORD-1002?"*.
   Expand `checkStockLevel` and `getOrderStatus` (or your server's discovered names). Confirm **out of stock**
   and **processing** respectively.

## Part C — Prepare connection reuse for pro-code

1. In `agents/procode/.env`, set `MCP_PROJECT_CONNECTION_NAME=apim-whisker-mcp`, using the actual connection
   name/ID recorded above. Do not put the subscription key into Python or YAML.
2. Keep `APIM_MCP_PATH=whisker-mcp`. These settings are read by `create_agent.py` when topic 4 creates the agent.
   No pro-code agent needs to exist yet.
3. Confirm the endpoint works in both Copilot and the Foundry Playground before continuing.

**Checkpoint:** five read-only tools are discoverable, live inventory/order calls succeed, and the Foundry
connection is ready for reuse. Continue to [topic 4](04-create-prompt-agent-code.md).

## Docs
- [MCP servers in APIM — overview](https://learn.microsoft.com/azure/api-management/mcp-server-overview)
- [Expose a REST API as an MCP server](https://learn.microsoft.com/azure/api-management/export-rest-mcp-server)
- [Expose and govern an existing MCP server](https://learn.microsoft.com/azure/api-management/expose-existing-mcp-server)
- [Secure access to MCP servers](https://learn.microsoft.com/azure/api-management/secure-mcp-servers)
- [Manage MCP servers programmatically (REST/Bicep)](https://learn.microsoft.com/azure/api-management/manage-mcp-servers-rest-api)
- [Use MCP servers in VS Code](https://code.visualstudio.com/docs/copilot/chat/mcp-servers)
