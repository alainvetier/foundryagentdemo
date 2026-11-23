<a id="05--pro-code-vs-code--foundry-toolkit--github-copilot"></a>

<a id="04--pro-code-vs-code--foundry-toolkit--github-copilot"></a>

# 4. Create a prompt agent with code

**Previous:** [03 — Create and connect Store MCP](03-connect-store-tools-mcp.md).
**Next:** [05 — Hosted agent](05-build-hosted-agent-framework.md).

**Goal:** build a prompt agent from repository configuration, invoke its returned version, and inspect it in VS Code.

For the notebook workflow, use Topic 4 of
[the runbook](whisker-works-demo-runbook.ipynb). It previews the definition and instructions inline,
creates `whiskers-concierge-pro-live`, and pins its returned name/version for chat and Topic 8 comparison.
The tested `whiskers-concierge-pro` is not changed. The first creation under an unused name is version 1;
repeat runs add versions. Choose an unused name in the preview cell if you want to start again at version 1.
Creation is approval-gated; opening the notebook does not create an agent.

**Starting point:** `whiskers-concierge` exists from topic 2. The pro-code agent is created in Part B below;
it is only visible in Part A if you already used the [optional shared-agent setup](00-setup-environment.md#6-optional-prepare-shared-agents-and-traces).
Complete [topic 3 — Create and connect Store MCP](03-connect-store-tools-mcp.md)
before starting this topic.

## Part A — Foundry Toolkit (visual, inside VS Code)

1. Activity Bar > **Foundry Toolkit** > sign in to Azure > **Set default project** > `whisker-works`.
2. Under **My Resources** (or **Agents**), expand the project and find `whiskers-concierge` (portal).
   If `whiskers-concierge-pro` is absent, that is expected before Part B; the infrastructure deployment does not create agents.
3. Open `whiskers-concierge` in **Agent Builder**: same model, instructions, tools as in the portal. Run a prompt in the playground.
4. For this repository, use the existing SDK source rather than **Developer Tools > Build > Create Agent**.
   That wizard scaffolds local files and its folder prompt is not a Foundry project selector. If exploring
   scaffolding separately, select a new, empty folder; do not generate over `agents/procode/`.
5. In Agent Builder: **View code** / generate client code for the agent (Python) — compare with [chat.py](../agents/procode/chat.py).
6. Open **Tool Catalog** to inspect MCP servers that can be reused by agents.

## Part B — Code + GitHub Copilot

Files: [agents/procode/](../agents/procode/) — `agent.yaml` (source of truth), `instructions.md`, `create_agent.py`, `chat.py`.
Copilot is primed by [.github/copilot-instructions.md](../.github/copilot-instructions.md).

From the workspace root, confirm [environment setup](00-setup-environment.md#3-deploy-azure-resources)
is complete: the virtual environment is installed and `agents/procode/.env` contains the deployment settings.
The `whisker-mcp` server must already be created and tested in
[topic 3](03-connect-store-tools-mcp.md);
`create_agent.py` configures the agent's MCP client, not the APIM server. Sign in with `az login` if needed.

```bash
cd agents/procode
source ../../.venv/bin/activate
python create_agent.py                 # first run creates v1; subsequent runs add a version
```

The commands in this guide target the original YAML-named agent. To isolate an experiment,
use `python create_agent.py --name whiskers-concierge-pro-live --output-json created-agent.json`.
The optional JSON output contains only the created `name`, `version`, and `model`, not credentials.
It is written only after successful creation; output-write errors are surfaced. Pass the returned name and
version explicitly to `chat.py --agent <name> --version <version>`. The notebook handles this handoff
automatically using a temporary file and removes it afterwards. A name override does not edit the source
YAML or change its model, instructions, or tools.

1. Wait for `Agent ready: name=whiskers-concierge-pro version=... model=gpt-4.1-mini`.
2. In Foundry Toolkit, refresh **My Resources / Agents** for `whisker-works`. You should now see both
   `whiskers-concierge` and `whiskers-concierge-pro`. The agent also appears in the Foundry portal's **Agents** list.
3. Open the newly created version of `whiskers-concierge-pro` and compare its model, instructions, file search,
   **Code Interpreter** (with `whisker-sales-2026.csv`), and MCP tool with the low-code agent.
   Both are versioned Foundry agents; only their authoring workflow differs.
   Send *"Do you have a heated bed in stock and what's the return
   policy if my cat hates it?"* in Agent Builder's playground and inspect the tool activity it exposes.
   This invokes the remote prompt agent; it is not local Python debugging. You can also use
   the terminal or notebook client to compare the experience, or as an alternative if the
   extension cannot open the created version. Do not edit or save the definition in Agent Builder:
   the repository YAML and instructions remain the source of truth.
4. In the same terminal, run:

   ```bash
   python chat.py                      # interactive, shows tools used + tokens
   ```

Try: *Do you have a heated bed in stock and what's the return policy if my cat hates it?*
→ Example tool summary: `[tools: mcp:whisker_store.listOrSearchProducts, mcp:whisker_store.checkStockLevel, file_search]`.
The agent can choose a different sequence of calls. Exact MCP names depend on the server's discovered tools;
see the [tool-name mapping](03-connect-store-tools-mcp.md#confirm-the-exposed-tool-names).

Code Interpreter is included by default in [agent.yaml](../agents/procode/agent.yaml), not added later as a
Copilot exercise. [create_agent.py](../agents/procode/create_agent.py) uploads the configured sales CSV and
attaches its file ID to an automatically managed Code Interpreter container. Paths in `code_interpreter.files`
are relative to `agents/procode/`, just like the knowledge paths; set `code_interpreter.enabled: false` to omit it.
Each creation run uploads the configured input files for the new version; the existing knowledge vector store
is reused.

If you created the pro-code agent before this change, rerun `python create_agent.py` to add a new version,
then refresh Toolkit / the portal and select that version. Existing versions are unchanged.

Test with: *"Use the sales CSV to calculate monthly revenue by category, plot it, and tell me which category
is growing fastest."* The terminal tool summary should include `code_interpreter_call`.
The terminal client prints text and tool usage; it does **not** render or download generated images.
To view the chart, open the new agent version in the **Foundry playground**, run the chart prompt there,
and use the generated image attachment to download the PNG (not a `/mnt/data` link).
Code Interpreter sessions have [additional charges](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/code-interpreter).

If the pro-code agent is still missing after creation, confirm Foundry Toolkit is viewing the same project as
`FOUNDRY_PROJECT_ENDPOINT` in `agents/procode/.env`, then refresh again. If creation failed, resolve the reported
error before continuing; refreshing cannot create the agent.

<a id="copilot-prompts-to-use-live-agent-mode"></a>

### Optional Copilot exercises (Agent mode)
1. *"Explain what create_agent.py does and which tools the agent gets."*
2. *"Update instructions.md so sales analysis also reports the strongest month for each category, using the existing Code Interpreter tool."*
   (Review the instruction change; run `python create_agent.py` → new version, then test a sales prompt.)
3. *"Use the whisker-works-via-apim MCP server to check stock for WW-012 and the status of ORD-1001."*
   (Copilot itself consumes the APIM-hosted MCP server — start it from [.vscode/mcp.json](../.vscode/mcp.json).)
4. *"Write a pytest that checks the agent answers the express shipping price correctly."*

> Optional: install the **Microsoft Foundry skill** for Copilot so it knows Foundry APIs
> ([docs](https://learn.microsoft.com/azure/foundry/how-to/develop/use-microsoft-foundry-skill)).

### Commit with GitHub Desktop
GitHub Desktop shows the Copilot changes as a diff → write a summary → **Commit to main** (or a branch) → **Push origin**.

## Docs
- [Foundry Toolkit: create an agent](https://learn.microsoft.com/azure/foundry/how-to/develop/create-agent-visual-studio-code)
- [Foundry Toolkit: prompt agent / Agent Builder](https://learn.microsoft.com/azure/foundry/how-to/develop/create-prompt-agent-visual-studio-code)
- [Set up a Foundry project in VS Code](https://learn.microsoft.com/azure/foundry/how-to/develop/set-up-foundry-project-visual-studio-code)
- [SDK quickstart](https://learn.microsoft.com/azure/foundry/quickstarts/get-started-code)
- [azure-ai-projects samples](https://github.com/Azure/azure-sdk-for-python/tree/main/sdk/ai/azure-ai-projects/samples/agents)
