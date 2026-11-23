<a id="demo-run-of-show"></a>

# Self-paced walkthrough

Explore **Build → Validate and improve → Govern → Bring it together** using the
[Jupyter notebook](whisker-works-demo-runbook.ipynb#learning-path) or the topic guides.
Follow the sequence for a complete walkthrough, or choose an activity and complete its prerequisites.
You do not need to deploy every optional agent or run a GitHub workflow.

## Start here

1. Clone the repository and review the tools, permissions, model quota, and cost guidance in
   [new-environment setup](00-setup-environment.md), or use
   [existing-environment setup](00b-setup-existing-environment.md) if you already have Foundry and APIM.
2. Deploy and verify the base infrastructure. Keep the generated `agents/procode/.env` private.
   The storefront product grid works after deployment; its chat additionally needs the default pro-code agent.
3. Use Bash from the repository root unless a step changes directory. Activate the root `.venv` for
   the notebook and pro-code scripts. Hosted local development uses its separate environment.
4. Choose the activities below. Create agents and connections when their topic requires them;
   the infrastructure deployment does not create all of them automatically.

## Activities and prerequisites

| # | Activity | Guide | Prerequisite | Verify before continuing |
|---|----------|-------|--------------|--------------------------|
| 1 | Agent building blocks | [01](01-agent-building-blocks.md) | None for reading | Distinguish model, knowledge, tools, state, and orchestration. |
| 2 | Prompt agent in the portal | [02](02-build-prompt-agent-foundry-portal.md) | Base infrastructure and model access | Policy answers cite knowledge; Code Interpreter returns a chart attachment. |
| 3 | Store tools over MCP | [03](03-connect-store-tools-mcp.md) | Base infrastructure; topic 2 for the low-code connection | Five read-only tools are discoverable; inventory and order queries execute tools. |
| 4 | Prompt agent from code | [04](04-create-prompt-agent-code.md) | Store MCP and its project connection from topic 3 | Record the created name/version and invoke that same version. |
| 5 | Hosted Agent Framework agent | [05](05-build-hosted-agent-framework.md) | Base infrastructure, Store MCP, `azd`, and project permissions | Deploy Kernel Panic, invoke it, and deny a purchase-order request without side effects. |
| 6 (optional) | Container Apps runtime | [06](06-optional-container-apps-agent.md) | Base infrastructure, Store MCP, and the guide's extra permissions | Verify actual tool calls, correlated traces, and APIM's declared-write denial. |
| 7 | Versions, traces, and evaluations | [07](07-versions-traces-evaluations.md) | Agent from topic 2; Store MCP for inventory cases; judge-model access | Trace the executed tools and retain baseline evaluation results. |
| 8 | Model changes and release lifecycle | [08](08-change-model-safely.md) | Topic 4 baseline for the notebook comparison | Compare exact versions of the same agent; inspect release gates separately from optional workflow activation. |
| 9 | Model governance | [09](09-govern-model-calls.md) | Base infrastructure and local settings | Gold succeeds; the Bronze test reports an APIM-enforced token limit. |
| 10 | Content Safety | [10](10-content-safety-gateway.md) | Model gateway and Content Safety backend | Inspect policy execution for a normal request and the controlled safety test. |
| 11 | MCP governance and optional approval | [11](11-govern-mcp-tools.md) | Store MCP; concierge agents for end-to-end checks | Verify tool access and rate limits; restore the normal limit after testing. |
| 12 | A2A governance | [12](12-govern-agent-to-agent-calls.md) | Base infrastructure and deployed wellness service | Import or reuse the A2A API, then verify its rewritten card and governed request. |
| 13 | Storefront and next steps | [Notebook activity](whisker-works-demo-runbook.ipynb#13-storefront-and-next-steps) | Default `whiskers-concierge-pro` and Store MCP | Combine product details and a real inventory check in the storefront. |

The [cat-food specialist](optional-cat-food-specialist.md) is a separate optional extension.
Topics 5 and 6 are not prerequisites for evaluation, model comparison, or model/MCP gateway exercises.
Reading the CI/CD samples needs no GitHub configuration; running them requires the separate configuration
and authorization described in their guide.

<a id="developer-tools-without-extending-the-session"></a>

## Choose a client

- **Notebook:** execute cells individually. Review each live action and set its explicit approval phrase
  only when you intend to run it. Do not use **Run All** against a shared environment.
- **Foundry portal or Toolkit:** open the exact agent/version created by the exercise.
  Keep YAML and instructions authoritative for code-created agents; do not save unrelated UI edits.
- **Terminal:** use the commands in the topic guide and record returned versions rather than assuming
  they are `1` and `2`.
- **Local Inspector:** debug the repository's hosted-agent source. The deployed Playground separately
  verifies the hosted runtime, identity, configuration, and network access. Local success does not prove deployment success.

## Pause and resume

- Keep your own record of the topic, agent name/version, and any temporary policy changes.
  Never record credentials in notes, committed files, or notebook output.
- After restarting the notebook kernel, rerun initialization. The isolated model-comparison path
  requires its preview, baseline, and candidate cells in order; it does not guess the latest version.
- Reuse existing resources after verifying their configuration. Repeating agent creation adds versions.
- Restore MCP `calls="30"` after a rate-limit experiment and allow its 60-second window to reset.
- Stop your local debugger when finished. Azure services may continue charging while you are paused;
  review cleanup before leaving an environment unused.

<a id="closing-message"></a>

## Storefront and next steps

If you followed the notebook's isolated pro-code path, its `whiskers-concierge-pro-live` agent does not
replace the storefront agent. Create the default agent using the topic 4 terminal instructions or the
[optional shared-agent setup](00-setup-environment.md#6-optional-prepare-shared-agents-and-traces).
Open the storefront URL printed by deployment and ask for a product recommendation with a stock check.
Verify both knowledge and Store MCP activity rather than relying on a fluent answer alone.

Foundry provides the agent platform for building, versioning, evaluating, and tracing agents.
APIM governs the model, tool, and agent traffic routed through its gateway. Use the
[FAQ](faq.md) and [references](references.md) to explore a capability further.

## If something breaks

| Problem | Next step |
|---------|-----------|
| Store MCP does not exist | Create it using topic 3 or the read-only setup script; inspect existing servers before rerunning configuration. |
| Toolkit cannot open the created version | Use notebook chat or Foundry portal with the same name/version. |
| Local Inspector is unavailable | Use the deployed Playground after completing hosted deployment; local debugging is optional. |
| Workflow configuration is not available | Use the isolated notebook version comparison or read the inactive samples without activating them. |
| Metrics have not arrived | Check the selected time range and ingestion delay; inspect APIM **Test > Trace** for request-level evidence. |
| Model quota or rate-limit error | Follow the retry delay and inspect model capacity and regional quota. Do not relax gateway controls to hide an upstream error. |
| Storefront chat cannot find its agent | Create the default YAML-named agent; the isolated notebook agent is separate. |

## Clean up

For a disposable environment you own, follow [new-environment cleanup](00-setup-environment.md#8-clean-up).
For reused/shared infrastructure, use the [existing-environment cleanup](00b-setup-existing-environment.md#7-clean-up-leave-shared-resources-tidy)
and verify the exact scope with its owner. Optional runtimes have their own targeted cleanup instructions.
