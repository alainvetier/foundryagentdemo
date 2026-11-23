<a id="02--low-code-create-an-agent-in-the-foundry-portal"></a>

# 2. Build a prompt agent in the Foundry portal

**Goal:** build `whiskers-concierge` with instructions, **knowledge** (file search) and **tools**
(code interpreter) — no code. Topic 3 adds live Store tools through APIM MCP.

Copy/paste values: [agents/lowcode/whiskers-concierge.md](../agents/lowcode/whiskers-concierge.md)

## Steps

1. Go to <https://ai.azure.com> and make sure the **new Foundry** experience toggle is on. Open project **whisker-works**.
2. **Build** (or **Agents**) > **Create agent**.
3. **Name**: `whiskers-concierge`. **Model**: `gpt-4.1-mini`.
4. **Instructions**: paste the instructions block from the low-code file.
5. **Knowledge** > **Add** > **Files** (file search) > upload the three files from `data/knowledge/`.
   Wait until indexing finishes (vector store status *completed*).
6. **Tools** > **Add** > **Code interpreter** > attach `data/sales/whisker-sales-2026.csv`.
7. **Save** — this creates **version 1** of the agent.
8. Test in the **Playground** with the starter prompts:
   - *What's your return policy if my cat ignores the new bed?* → cites `store-policies.md` (Cat Indifference Guarantee)
   - *Plot monthly revenue per category…* → code interpreter displays a chart and returns a PNG attachment
   - *Can I order lilies for my cat's birthday?* → grounded refusal (toxic)
   - Leave live stock and order-status prompts for topic 3.

## Next

Continue to [topic 3 — Create and connect Store MCP](03-connect-store-tools-mcp.md).
That guide contains server creation, VS Code testing, and the Foundry connection in one place.

<a id="talking-points"></a>

## Verify what you built
- No code; agent is a **versioned** resource in the project.
- Knowledge = file search with a managed vector store (or bring Azure AI Search / Foundry IQ).
- Tools are pluggable: built-in (code interpreter, web search), OpenAPI, MCP, A2A, Toolboxes.
- Expand the **tool call** details in the playground response and identify which file or tool was used.

## Chart display and download

- Code Interpreter files live under `/mnt/data` in an isolated sandbox. A Markdown link such as
  `[/mnt/data/chart.png](sandbox:/mnt/data/chart.png)` can be rewritten by the portal as
  `https://ai.azure.com/mnt/data/chart.png`, which returns **404**. Do not use that link.
- The plotting instruction explicitly asks Code Interpreter to call `plt.show()` for an inline preview and save a PNG.
  Depending on the current Playground UI, the result can appear as an inline chart, an image attachment chip, or both.
- Download the chart by selecting the generated `.png` attachment chip below the response (for example,
  `monthly_revenue_by_category_2026.png`), not the `Download the chart image` link in the response text.
- If an existing agent still generates the bad link, update its instructions from
  `agents/lowcode/whiskers-concierge.md`, save a new version, start a new Playground conversation, and retry the
  updated starter prompt.

## Docs
- [File search tool](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/file-search)
- [Connect agents to MCP servers](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/model-context-protocol)
- [Tool best practices](https://learn.microsoft.com/azure/foundry/agents/concepts/tool-best-practice)
