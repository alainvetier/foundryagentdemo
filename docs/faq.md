# Microsoft Foundry and Whisker Works FAQ

The first section answers general questions about Microsoft Foundry and AI agents; the remaining sections cover
the Whisker Works demo and setup. For the complete walkthrough, see the
[self-paced notebook](whisker-works-demo-runbook.ipynb); the [walkthrough overview](demo-run-of-show.md)
lists prerequisites, optional paths, and verification steps.

## Microsoft Foundry and agents

These are general platform questions; the answers apply beyond the Whisker Works demo. Foundry features and
availability can vary by region, model, and release.

### What is Microsoft Foundry?

Microsoft Foundry is Microsoft's platform for building, customizing, evaluating, deploying, and operating
generative AI applications and agents. It brings model discovery and deployment together with agent development,
evaluation, and observability. See [What is Microsoft Foundry?](https://learn.microsoft.com/azure/foundry/what-is-foundry).

### What is a Foundry project?

A project is a workspace for organizing AI application work, including agent definitions, connections, and
project-level settings. It is associated with a Foundry resource, which provides the Azure resource boundary for
the project. The exact resources and capabilities available depend on the project and its configuration. See
[Create Foundry projects](https://learn.microsoft.com/azure/foundry/how-to/create-projects).

### What is an AI agent?

An AI agent is an application that uses a model to interpret a request and decide what to do next. It can combine
instructions, conversation context, knowledge sources, and tools, then use tool results to produce a response.
Unlike a model alone, an agent can take actions through the tools it is given. See the
[Foundry agents overview](https://learn.microsoft.com/azure/foundry/agents/overview).

### How is an agent different from a model?

A model generates or transforms content from inputs. An agent is a larger application pattern that uses a model
with instructions, context, and optional tools, and coordinates the steps needed to respond. The model does not
automatically have access to a user's data or systems; those capabilities must be connected and permissioned.

### What kinds of agents can I build or run with Foundry?

Foundry supports multiple development and runtime approaches, including prompt-configured agents and agents
built with your own code and hosted on Foundry. Depending on current availability, voice and managed-harness
options may also be available. The approaches differ in how much orchestration Foundry manages versus how much
the developer implements. Check the [agents overview](https://learn.microsoft.com/azure/foundry/agents/overview)
for current options.

### When should I use a prompt agent versus a hosted agent?

Use a prompt agent when its configuration and supported tools meet your needs and you want Foundry to manage
the agent orchestration. Consider a hosted agent when you need custom application logic, framework flexibility,
or control over orchestration in code. Assess operational, security, and deployment requirements as well as
development effort; neither approach is universally best.

### What can an agent use as knowledge or tools?

An agent can be grounded with supported knowledge sources and connected to supported tools. Tool options can
include built-in capabilities, APIs, MCP servers, or other agents, depending on the agent type and configuration.
Only connected and authorized sources are available to it. See Foundry's guides for
[file search](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/file-search),
[MCP](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/model-context-protocol), and
[A2A tools](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/agent-to-agent).

### How does grounding help an agent answer accurately?

Grounding supplies relevant information from sources selected for the application, such as documents or a
search index. It can make responses more relevant to that information, but it does not guarantee correctness:
source quality, retrieval, instructions, and the model all matter. Important answers should be evaluated and
verified against authoritative sources.

### Does an agent remember users between conversations?

Conversation context can be included to support multi-turn interactions, but that is not the same as durable
memory across users or sessions. Persistent memory requires an application design for what to store, how long to
retain it, access controls, and user consent; do not assume it is enabled automatically.

### Can an agent take actions or make changes to systems?

It can only attempt actions exposed through its configured tools and the permissions available to those tools.
For consequential or irreversible actions, design explicit authorization, validation, least-privilege access,
and human approval where appropriate. A model-generated response alone is not proof that an action succeeded.

### Can agents collaborate with other agents?

Yes, agent-to-agent patterns can delegate work to other agents through supported integrations and protocols.
The calling application still needs to manage authorization, trust boundaries, failure handling, and which actions
each agent may take. See [connect to an A2A agent endpoint](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/agent-to-agent).

### How do I test whether an agent is good enough?

Test representative prompts and expected behaviors, including failure and safety cases. Foundry provides
evaluation capabilities and built-in evaluators, but teams should select metrics and human review appropriate
to the application. Evaluation results are evidence for a decision, not a guarantee of future performance. See
[evaluate your AI agents](https://learn.microsoft.com/azure/foundry/observability/how-to/evaluate-agent).

### How can I inspect agent behavior after deployment?

Use tracing and monitoring to inspect supported request flows, model calls, tool calls, errors, and timing.
What is captured depends on the runtime and telemetry configuration. Avoid logging secrets or unnecessary
sensitive data, and configure retention and access to meet your organization's requirements. See
[set up agent tracing](https://learn.microsoft.com/azure/foundry/observability/how-to/trace-agent-setup).

### How should I secure an agent?

Treat an agent as an application with access to data and actions: use identity-based access where supported,
grant least privilege, secure connections and secrets, validate tool inputs, restrict network access where
required, and apply appropriate safety and monitoring controls. Review your organization's policies and the
current Foundry security guidance before production use.

<a id="about-the-session"></a>

## About the walkthrough

### What is Whisker Works?

Whisker Works is a fictional cat-products retailer used to make agent and gateway concepts concrete. Its sample
catalog, policies, sales data, and customer conversations are demo assets, not a real commerce service.

### What does the demo show?

It shows how to build and operate agents with Microsoft Foundry, then govern their access to models, tools, and
other agents through Azure API Management (APIM). Choose exercises for portal-built prompt agents,
a pro-code agent, a hosted agent, MCP tools, an A2A agent, safety controls, evaluation, and tracing.

### Do I need Azure or developer tools to follow along?

You can read the documentation and inspect the source without Azure access. Running the hands-on exercises
requires an Azure subscription and the tools in the [setup guide](00-setup-environment.md#1-prerequisites),
including Azure CLI, Python 3.11+, and VS Code. The hosted-agent path also uses `azd`;
Docker is required only for container builds, not Foundry remote code deployment.

### Is every segment required?

No. Choose the capabilities you want to explore, then complete their prerequisites in the
[walkthrough overview](demo-run-of-show.md). The low-code and pro-code topics use the same Store MCP setup;
hosted-agent and Container Apps deployment are optional. Evaluation and model comparison do not require those
optional runtimes. Pause and return to any topic when its prerequisites are ready.

## Agents, data, and tools

### What makes this an agent rather than a regular chatbot?

An agent combines a model and instructions with optional knowledge and tools. It can decide whether to answer
from its knowledge or call a tool, inspect the result, and then respond. The [agent building-blocks guide](01-agent-building-blocks.md)
maps these pieces to the demo.

### What is the difference between knowledge and tools?

Knowledge is reference material the agent searches, such as store policies and product descriptions. Tools let
the agent retrieve current store data or perform a defined action, such as checking inventory. The sales CSV is used
for historical analysis; it is not a live inventory source.

### What is the difference between prompt agents and hosted agents?

A prompt agent is configured declaratively with a model, instructions, and tools; Foundry runs its orchestration.
A hosted agent is application code (here, using Microsoft Agent Framework) that implements its own orchestration
and runs on Foundry-managed compute. See [prompt vs hosted agents](05-build-hosted-agent-framework.md#prompt-agents-vs-hosted-agents).

### What are MCP and A2A?

MCP standardizes how an agent discovers and calls tools, such as the Store API. A2A lets agents communicate with
other agents; this demo includes a feline wellness agent. APIM can govern both kinds of traffic. See the
[MCP guide](03-connect-store-tools-mcp.md) and [A2A guide](12-govern-agent-to-agent-calls.md).

### What can I ask Whiskers?

Try questions about store policies, product details, live product availability, order status, or cat-care basics.
You can also ask for a chart or summary from the historical sales dataset. Product IDs look like `WW-001`; sample
order IDs look like `ORD-1001`. Health answers are general guidance, not a veterinary diagnosis.

### Where do answers come from?

Policies, product descriptions, and cat-care guidance are grounded in the demo knowledge files. Product lists,
stock, order status, and cat facts come from the Store API when its tools are connected. Sales analysis uses the
provided historical CSV. If a data source is unavailable, the agent should not guess live stock or order status.

### Is the inventory or order history connected to a real store?

No. The Store API is a demo service with sample data. Its product and order state is held in memory and resets
when the API restarts; it is not a persistent commerce backend.

### Can Whiskers place an order?

The standard Store MCP setup is read-only and deliberately excludes the `placeOrder` operation. An optional
segment demonstrates a separate, Gold-only write tool with human approval. For that flow, the agent must receive
explicit confirmation of the products, quantities, customer name, and shipping country, and must not claim success
until the tool confirms it. See [MCP governance and approval](11-govern-mcp-tools.md#part-d--optional-write-server-with-human-approval).

### What is the sales CSV for?

`whisker-sales-2026.csv` is historical demo data for summaries, trends, and charts through Code Interpreter. It
does not report current stock, current orders, or live sales.

## Gateway and safety

### What does APIM add?

APIM acts as a control plane in front of model, tool, and agent calls. The demo shows controls such as identity
and subscriptions, rate limits, content safety, tool availability, token metrics, and request tracing. The exact
policies depend on the segment being demonstrated.

### What are Bronze and Gold?

They are APIM products used to demonstrate different access and throttling policies. Some demo APIs are Gold-only;
the Store MCP read tools can be associated with both products. They are demo access tiers, not store loyalty
programs or production service-level guarantees.

### Is the demo safe to use with real customer data?

Use the provided sample data. Do not enter secrets, payment details, or personal or confidential production data
into the demo. This kit is a learning environment; it does not by itself establish production privacy, security,
or compliance controls.

### Why might a feature or portal screen look different?

Some capabilities used in the kit—including APIM A2A and some Foundry agent features—are preview features, and
the portals may change. The repository's [references](references.md) and the linked Microsoft documentation are
the best sources for current product details.

## Setup and troubleshooting

### How do I set it up?

For a new environment, follow [00 — Set up the demo environment](00-setup-environment.md). If you already have
Foundry and APIM, use [00b — Existing environment](00b-setup-existing-environment.md) to reuse them. The
[README quick start](../README.md#quick-start) has the command entry points.

### What does setup cost?

The README gives an estimate for the new-environment configuration, based on a specific region and published
rates, plus the key cost caveats. Actual charges vary by region, subscription, agreement, runtime, and usage.
APIM and App Service can continue to incur charges while idle, so review the [cost and tier guidance](00-setup-environment.md#cost-and-tier-choice)
and clean up resources when finished. Existing-environment mode keeps the existing APIM tier.

### Why did a model request return 401 just after deployment?

Azure role assignments can take a few minutes to propagate. Wait and retry; if the issue persists, check the
identities and roles in the [setup troubleshooting section](00-setup-environment.md#troubleshooting).

### Why did I get a 429 or 403?

A **429** usually means a configured rate limit was reached; it is an expected governance demonstration, not
necessarily an outage. A **403** may be a Content Safety policy block or another authorization decision. Inspect
the APIM trace and the relevant segment's policy before changing thresholds.

### Why can't the MCP client connect?

Check that the MCP server exists and its URL is correct. In the VS Code example, provide the APIM hostname only
when prompted—not a URL scheme or path—and use the right subscription key. If the server was changed, refresh
tool discovery or restart the client. The [MCP guide](03-connect-store-tools-mcp.md) has concrete setup and
troubleshooting steps.

### How do I clean up after the demo?

For a new environment, use the cleanup command in the [README](../README.md#quick-start). If using a shared
existing APIM, remove only the demo's `whisker-*` configuration with the existing-environment cleanup procedure;
do not delete shared resources.

### Where should I look for the full instructions?

Start with the [self-paced notebook](whisker-works-demo-runbook.ipynb) for executable exercises,
the [walkthrough overview](demo-run-of-show.md) for prerequisites and troubleshooting, and the
[README](../README.md) for architecture, setup modes, scripts, and the repository map.
