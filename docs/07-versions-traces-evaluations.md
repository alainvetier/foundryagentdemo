<a id="04--show-the-agent-details-in-foundry"></a>

<a id="07--show-the-agent-details-in-foundry"></a>

# 7. Versions, traces, and evaluations

**Previous:** [06 — Optional Container Apps runtime](06-optional-container-apps-agent.md),
or [05 — Hosted agent](05-build-hosted-agent-framework.md) if skipping the optional runtime.
**Next:** [08 — Update the agent model](08-change-model-safely.md).

## Prepare trace data

Application Insights is connected by the infrastructure deployment, but it only shows runs created after the
connection exists. After creating the agent you want to inspect, generate representative trace data:

```bash
source .venv/bin/activate
python scripts/seed-agent-traces.py
```

By default this seeds `whiskers-concierge`. To seed both saved concierge agents, add
`--agents whiskers-concierge whiskers-concierge-pro` after both exist.
The script prints each conversation and response ID. Allow several minutes for ingestion, then open
**whisker-works** > **Agents** > `whiskers-concierge` > **Traces**, select **7D**, and refresh. Search for the
printed conversation ID if needed.

## Walkthrough

Open **whisker-works** project > **Agents** > `whiskers-concierge` and walk through:

| Area | What to inspect | What to verify |
|------|--------------|---------|
| **Overview / Definition** | Model, instructions, tools, knowledge | The saved configuration matches the agent you created. |
| **Versions** | Version list, diff between versions | Each save creates an immutable version; record the version you test. |
| **Playground** | Run a prompt, expand tool calls and file-search citations | Identify which tool or knowledge file contributed to the answer. |
| **Conversation view** | Open the seeded conversation and its four responses | Requests and responses belong to the same conversation. |
| **Trace view** | Expand a seeded response into model, file-search, and MCP spans; inspect latency and tokens | The execution path and available spans are also visible in App Insights. |
| **Monitoring** | Token usage, run counts, latency, error rates | Operational view |
| **Evaluations** | Run the evaluation below with `data/eval/whisker-eval.jsonl` | Save baseline scores before changing the model. |
| **Guardrails / Content filters** | Default content filter on the model deployment | Safety at the model; APIM adds a second line at the gateway |
| **Endpoint / Code** | "View code" snippet for the agent (Responses API with `agent_reference`) | Compare the generated client with the repository's pro-code client. |
| **Publish / Share** (optional) | Publish to Teams/M365 Copilot or as an endpoint | Distribution |

Compare the pro-code agent created in [topic 4 Part B](04-create-prompt-agent-code.md#part-b--code--github-copilot)
with the low-code agent: both have the **same** resource structure. In the notebook workflow, inspect the
captured `whiskers-concierge-pro-live` version; do not substitute the pre-created storefront agent.

## Run the agent evaluation

<a id="before-the-demo"></a>

### Evaluation prerequisites

1. Confirm `whiskers-concierge` is saved and published with the version you want to evaluate.
2. Confirm its three knowledge files are indexed. To evaluate the stock and order-status rows successfully, also
   complete [topic 3 — Create and connect Store MCP](03-connect-store-tools-mcp.md).
3. Confirm the project has an Azure OpenAI connection and a judge model deployment. Use `gpt-4.1-mini` for this
   small demo evaluation.
4. Keep [whisker-eval.jsonl](../data/eval/whisker-eval.jsonl) ready to upload. It contains eight rows:
   - `query`: the prompt sent to the agent.
   - `ground_truth`: the expected answer used by reference-based evaluators.
   - `must_include`: used by the local `compare_models.py` demo; it is not required by the portal evaluators.

### Create the evaluation

1. In project **whisker-works**, open **Agents** > `whiskers-concierge` > **Evaluation** and select **Create**.
   You can also use the project navigation: **Evaluation** > **Create**.
2. For **Evaluation target**, select **Agent**.
3. Select agent **whiskers-concierge** and the version you want to evaluate. Do not select **Dataset** as the target:
   the Agent target runs each query and captures the generated response and tool activity.
4. For **Evaluation scope**, select **Individual turns**. This enables per-response and tool-use evaluators.
5. For **Data source**, select **Existing dataset**.
6. Select an existing project data asset or upload
   [whisker-eval.jsonl](../data/eval/whisker-eval.jsonl). Confirm the preview shows eight rows and the columns
   `query`, `must_include`, and `ground_truth`.

### Configure the agent and fields

1. In **Configure agents**, leave the saved system instructions unchanged.
2. Set **User prompt** to `{{item.query}}`. This sends the `query` value from each JSONL row to the agent.
3. In **Field mapping**, verify:

   | Evaluation field | Dataset/generated value |
   |---|---|
   | `query` | `query` |
   | `ground_truth` | `ground_truth` |
   | `response` | Agent-generated response |
   | `tool_calls` | Captured from the agent run |
   | `tool_definitions` | Captured from the selected agent |

4. Leave `must_include` unmapped. If a required field is marked **Unassigned**, correct it before continuing.

### Select evaluators

Use these evaluators to inspect different quality dimensions:

- **Relevance** — does the response address the query?
- **Response Completeness** — does it provide the necessary details?
- **Groundedness** — is the answer supported by retrieved knowledge or tool context?
- **Task Adherence** — did the agent follow its instructions and constraints?
- **Tool Call Accuracy** — did it select and call the appropriate tool correctly?

When the portal asks for an evaluator or judge model, select `gpt-4.1-mini`. Evaluator availability can vary by
region and portal version; if **Groundedness** or **Tool Call Accuracy** requires a field that the run cannot
provide, remove only that evaluator and continue with the other four.

### Submit and monitor

1. Name the run `whiskers-concierge-v<version>-baseline`, replacing `<version>` with the selected agent version.
2. Review the target, version, eight-row dataset, field mappings, judge model, and evaluators.
3. Select **Submit**.
4. Open **Evaluation** in the project navigation and wait for the run status:
   - **In Progress** — the agent and judge model are still processing rows.
   - **Completed** — all selected evaluators finished.
   - **Partial** — some evaluators failed; open the run and inspect the evaluator error.
   - **Failed** — check field mappings, model quota, permissions, and agent/tool availability.

<a id="present-the-results"></a>

### Inspect the results

1. Open the completed run and start with the aggregate score cards.
2. Open the row for *"What is your return policy for opened treats?"*. Inspect its query, generated response,
   ground truth, evaluator scores, and file-search/tool evidence.
3. Sort or filter by the lowest score and open that row. Use the evaluation evidence to identify
   a specific prompt, grounding, or tool problem rather than only reporting an average.
4. If MCP is configured, inspect the stock or order-status row and its tool call. If MCP is not configured,
   those two rows should fail or score lower because the agent is instructed not to invent live data. This is an
   expected configuration gap, not a model hallucination.
5. Record this run as the baseline. In topic 8, run the same dataset against the new agent version and compare the
   scores before promoting it.

Treat **85% or better Task Adherence** as an illustrative target, not a production release guarantee.
With only eight rows, inspect individual failures rather than treating the percentage as statistically rigorous.

### Evaluation troubleshooting

| Problem | Check |
|---|---|
| Dataset does not appear | Upload it from **Data** first, then return to **Existing dataset** and refresh. |
| `query` or `ground_truth` is unassigned | Manually map it to the identically named JSONL column. |
| Tool evaluator is partial/failed | Confirm **Individual turns** scope and that `tool_calls` and `tool_definitions` are captured from the Agent target. |
| Stock/order rows score poorly | Add the `whisker_store` MCP tool, verify its APIM subscription key, save a new agent version, and rerun. |
| Groundedness is unavailable | Remove it for this run or evaluate existing traces that contain retrieved context. |
| Evaluation stays queued or fails with quota | Confirm the judge-model deployment has quota; retry with `gpt-4.1-mini`. |
| Permission error | Confirm your identity has **Foundry User** (formerly Azure AI User) or a higher project role. |

## If no data appears

- Confirm the **Connect** banner is absent and `whisker-appi-xxxx` is the project's Application Insights connection.
- Set the date range to **7D**; the default **Last Day** can exclude earlier test traffic around timezone boundaries.
- Run `python scripts/seed-agent-traces.py --agents whiskers-concierge` again and wait several minutes.
- If the portal reports authorization errors, verify the project managed identity has **Log Analytics Reader** and
  **Privileged Monitoring Data Reader** on the connected Application Insights resource.

## Docs
- [Tracing in Foundry](https://learn.microsoft.com/azure/foundry/observability/how-to/trace-agent-setup)
- [Evaluate your AI agents](https://learn.microsoft.com/azure/foundry/observability/how-to/evaluate-agent)
- [Run evaluations from the portal](https://learn.microsoft.com/azure/foundry/how-to/evaluate-generative-ai-app)
- [Built-in evaluators](https://learn.microsoft.com/azure/foundry/concepts/built-in-evaluators)
