<a id="08--demo-azure-ai-content-safety-through-api-management"></a>

<a id="10--demo-azure-ai-content-safety-through-api-management"></a>

# 10. Content Safety at the gateway

**Previous:** [09 — Model gateway governance](09-govern-model-calls.md).
**Next:** [11 — MCP governance and approval](11-govern-mcp-tools.md).

Use this topic when Azure API Management (APIM) and an Azure AI Content Safety resource already exist. It adds no Azure resources. APIM's `llm-content-safety` policy checks requests (and optionally responses) as they pass through an API, then blocks unsafe content before it reaches the backend.

This walkthrough uses the existing **Foundry Models (AI Gateway)** API. It demonstrates Prompt Shields and harm-category thresholds at the gateway; it does not expose Content Safety's text-analysis REST API as a general-purpose proxy.

## Prerequisites

- An APIM instance on a tier that supports `llm-content-safety` and a subscription key for the API being tested.
- An Azure AI Content Safety resource with its endpoint available, for example `https://<resource-name>.cognitiveservices.azure.com`.
- Permission to configure APIM backends and assign roles on the Content Safety resource.
- For this repo's test command, Python dependencies installed and `agents/procode/.env` populated as described in [00b — existing environment](00b-setup-existing-environment.md).

## Configure the Content Safety backend

1. In the Azure portal, open the APIM instance and enable its **system-assigned managed identity** if it is not already enabled.
2. Open the Content Safety resource > **Access control (IAM)**. Assign **Cognitive Services User** to the APIM managed identity at the Content Safety resource scope. Allow time for the role assignment to propagate.
3. In APIM, open **Backends** and select the backend referenced by your policy. In this repo it is `whisker-content-safety`.
   - Set the backend URL to the Content Safety resource endpoint, not the Foundry model endpoint.
   - Enable managed identity authentication and set the audience/resource to exactly `https://cognitiveservices.azure.com`.

If the backend is shared or used by another API, create a separate backend for this demo instead of changing it; update the policy's `backend-id` to that backend's ID. Do not put a Content Safety key in the policy or client request.

## Apply the policy

On the target API, open **Policies** and place the policy in the `inbound` section. This minimal example checks incoming prompts for the listed harm categories and Prompt Shield attacks:

```xml
<llm-content-safety backend-id="whisker-content-safety" shield-prompt="true">
    <categories output-type="EightSeverityLevels">
        <category name="Hate" threshold="4" />
        <category name="Violence" threshold="4" />
        <category name="SelfHarm" threshold="4" />
        <category name="Sexual" threshold="4" />
    </categories>
</llm-content-safety>
```

The existing [models API policy](../apim/policies/models-api-policy.xml) already contains this check. If that policy is deployed, keep it and configure its backend as above. The thresholds are a demo starting point: with eight severity levels, a category is blocked at its threshold or higher. Adjust them for your service's requirements and validate with approved test samples. To also inspect model responses, see the policy's `enforce-on-completions` option; streaming responses have different blocking behavior.

<a id="demo"></a>

## Test the safety policy

1. In APIM, open **Backends** > `whisker-content-safety` and verify the resource endpoint and managed identity authentication. On the Content Safety resource's **Access control (IAM)** page, verify the APIM identity's role assignment.
2. Open **APIs** > **Foundry Models (AI Gateway)** > **Policies**. Locate the inbound `llm-content-safety` policy, Prompt Shields setting, and category thresholds.
3. Send a normal request through the gateway:
   ```bash
   python scripts/test-gateway.py basic
   ```
   It should complete normally. Then send the included Prompt Shields test:
   ```bash
   python scripts/test-gateway.py safety
   ```
   A detected attack is blocked with `403` before the request reaches the model. In the APIM API **Test** trace, inspect the policy execution and failure. Detection can vary as the service and thresholds evolve.
4. To demonstrate harm-category thresholds, use approved Content Safety sample inputs in a request through the same API. Compare a below-threshold result with a blocked result in the APIM trace; don't send test prompts directly to the model endpoint.

The client only needs its APIM subscription key. APIM authenticates to Content Safety with managed identity, so the Content Safety credential stays out of client code and configuration.

## Troubleshooting

| Symptom | Check |
|---|---|
| Backend authentication error | APIM managed identity has **Cognitive Services User** on the Content Safety resource; audience is exactly `https://cognitiveservices.azure.com`. |
| Policy cannot reach the service | Backend URL is the Content Safety resource endpoint, APIM can reach it, and the backend ID matches the policy. |
| Unexpected `403` on benign input | Review the APIM trace and category thresholds; model-deployment content filters can also independently return `403`. |
| Prompt Shield test is not blocked | Confirm `shield-prompt="true"`, the active API policy, backend identity/endpoint, and APIM trace. Detection behavior may vary. |

## References

- [Enforce content safety checks on LLM requests](https://learn.microsoft.com/azure/api-management/llm-content-safety-policy)
- [Use managed identities in API Management](https://learn.microsoft.com/azure/api-management/api-management-howto-use-managed-service-identity)
- [Azure AI Content Safety overview](https://learn.microsoft.com/azure/ai-services/content-safety/overview)