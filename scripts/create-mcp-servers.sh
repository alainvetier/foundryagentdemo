#!/usr/bin/env bash
# BACKUP PLAN for docs/03: creates the MCP servers in APIM programmatically
# (the live demo does the same thing in the portal).
#  1. whisker-mcp : REST API (Whisker Works Store API) exposed as MCP tools
#  2. learn-mcp   : existing remote MCP server (Microsoft Learn) proxied/governed by APIM
# Usage: ./scripts/create-mcp-servers.sh        (READ_ONLY=true to skip the placeOrder tool)
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source agents/procode/.env; set +a

APIM_RG="${APIM_RG:-$RG}"
API_VERSION="2025-09-01-preview"
SUB_ID="${AZURE_SUBSCRIPTION_ID:-}"
if [[ -z "$SUB_ID" ]]; then
  SUB_ID=$(az account show --query id -o tsv)
fi
APIM_ID="/subscriptions/$SUB_ID/resourceGroups/$APIM_RG/providers/Microsoft.ApiManagement/service/$APIM_NAME"
BASE="https://management.azure.com$APIM_ID"
echo "==> Target subscription: $SUB_ID; resource group: $APIM_RG; APIM: $APIM_NAME"
if ! az apim show --subscription "$SUB_ID" -g "$APIM_RG" -n "$APIM_NAME" --query id -o tsv; then
  echo "ERROR: Cannot access the target APIM. Check AZURE_SUBSCRIPTION_ID, APIM_RG and APIM_NAME in agents/procode/.env, and Azure CLI sign-in/permissions." >&2
  exit 1
fi
TMP=$(mktemp -d)

put() { az rest --subscription "$SUB_ID" --method put --uri "$1?api-version=$API_VERSION" --headers "If-Match=*" --body "@$2" -o none; }

echo "==> Creating REST-backed MCP server 'whisker-mcp'"
cat > "$TMP/server.json" <<'EOF'
{"properties":{"type":"mcp","path":"whisker-mcp","displayName":"Whisker Works MCP","description":"Store tools (catalog, inventory, orders, cat facts) for AI agents","protocols":["https"],"subscriptionRequired":true}}
EOF
put "$BASE/apis/whisker-mcp" "$TMP/server.json"

az apim api operation list --subscription "$SUB_ID" -g "$APIM_RG" --service-name "$APIM_NAME" --api-id whisker-works-api \
  --query "[].{name:name, description:description}" -o json > "$TMP/ops.json"

python3 - "$TMP" "$APIM_ID" "${READ_ONLY:-false}" <<'PY'
import json, sys, pathlib
tmp, apim_id, read_only = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3] == "true"
for op in json.loads((tmp / "ops.json").read_text()):
    if read_only and op["name"].lower() == "placeorder":
        continue
    body = {"properties": {"displayName": op["name"], "description": op["description"] or op["name"],
            "operationId": f"{apim_id}/apis/whisker-works-api/operations/{op['name']}"}}
    (tmp / f"tool-{op['name']}.json").write_text(json.dumps(body))
policy = pathlib.Path("apim/policies/mcp-tools-policy.xml").read_text()
(tmp / "policy.json").write_text(json.dumps({"properties": {"format": "rawxml", "value": policy}}))
PY

for f in "$TMP"/tool-*.json; do
  tool=$(basename "$f" .json); tool=${tool#tool-}
  echo "    + tool $tool"
  put "$BASE/apis/whisker-mcp/tools/$tool" "$f"
done
put "$BASE/apis/whisker-mcp/policies/policy" "$TMP/policy.json"

echo "==> Creating passthrough MCP server 'learn-mcp' (Microsoft Learn)"
cat > "$TMP/learn-backend.json" <<'EOF'
{"properties":{"description":"Microsoft Learn MCP base URL; the message endpoint adds /mcp","protocol":"http","url":"https://learn.microsoft.com/api"}}
EOF
put "$BASE/backends/whisker-learn-mcp" "$TMP/learn-backend.json"
cat > "$TMP/learn.json" <<'EOF'
{"properties":{"type":"mcp","path":"learn-mcp","displayName":"Microsoft Learn MCP (governed)","description":"Existing remote MCP server proxied by APIM","protocols":["https"],"backendId":"whisker-learn-mcp","subscriptionRequired":true,"mcpProperties":{"transportType":"streamable","endpoints":{"message":{"uriTemplate":"/mcp"}}}}}
EOF
put "$BASE/apis/learn-mcp" "$TMP/learn.json"
put "$BASE/apis/learn-mcp/policies/policy" "$TMP/policy.json"

echo "==> Adding MCP servers to products"
for product in whisker-gold whisker-bronze; do
  for api in whisker-mcp learn-mcp; do
    az rest --subscription "$SUB_ID" --method put --uri "$BASE/products/$product/apis/$api?api-version=$API_VERSION" -o none
  done
done

rm -rf "$TMP"
echo "Done:"
echo "  $APIM_GATEWAY_URL/whisker-mcp/mcp"
echo "  $APIM_GATEWAY_URL/learn-mcp/mcp"
