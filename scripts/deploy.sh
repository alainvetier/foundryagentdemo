#!/usr/bin/env bash
# Deploys the Whisker Works demo and writes agents/procode/.env
#
# Mode 1 - everything new (default):
#   PUBLISHER_EMAIL=you@contoso.com [RG=rg-whisker-works] [LOCATION=southeastasia] ./scripts/deploy.sh
#
# Mode 2 - reuse EXISTING Foundry + APIM (docs/00b-setup-existing-environment.md):
#   FOUNDRY_ACCOUNT=<name> FOUNDRY_RG=<rg> FOUNDRY_PROJECT=<project> \
#   APIM_NAME=<name> APIM_RG=<rg> [RG=rg-whisker-works] [LOCATION=...] \
#   [CREATE_MODEL_DEPLOYMENTS=true] [CHAT_MODEL=gpt-4.1-mini] [NEW_MODEL=gpt-5-mini] \
#   [CONNECT_FOUNDRY_APP_INSIGHTS=true] [MODELS_API_PATH=models] [STORE_API_PATH=store] \
#   [GLOBAL_APIM_DIAGNOSTICS=false] ./scripts/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

RG="${RG:-rg-whisker-works}"
ENABLE_CONTROL_TAGS="${ENABLE_CONTROL_TAGS:-true}"
case "$ENABLE_CONTROL_TAGS" in
  true) GROUP_TAG_ARGS=(--tags CostControl=Ignore SecurityControl=ignore) ;;
  false) GROUP_TAG_ARGS=() ;;
  *) echo "ENABLE_CONTROL_TAGS must be true or false"; exit 1 ;;
esac
API_VERSION="2024-06-01-preview"
EXISTING_MODE=false
[[ -n "${FOUNDRY_ACCOUNT:-}" && -n "${APIM_NAME:-}" ]] && EXISTING_MODE=true

echo "==> Subscription: $(az account show --query name -o tsv)"
USER_ID=$(az ad signed-in-user show --query id -o tsv)

if $EXISTING_MODE; then
  : "${FOUNDRY_RG:?Set FOUNDRY_RG}" "${FOUNDRY_PROJECT:?Set FOUNDRY_PROJECT}" "${APIM_RG:?Set APIM_RG}"
  echo "==> Existing mode: Foundry '$FOUNDRY_ACCOUNT/$FOUNDRY_PROJECT', APIM '$APIM_NAME'"

  echo "==> Pre-flight checks"
  KIND=$(az cognitiveservices account show -g "$FOUNDRY_RG" -n "$FOUNDRY_ACCOUNT" --query kind -o tsv)
  [[ "$KIND" == "AIServices" ]] || { echo "Foundry account must be kind AIServices (found: $KIND)"; exit 1; }
  FOUNDRY_ID=$(az cognitiveservices account show -g "$FOUNDRY_RG" -n "$FOUNDRY_ACCOUNT" --query id -o tsv)
  az rest --method get --uri "https://management.azure.com$FOUNDRY_ID/projects/$FOUNDRY_PROJECT?api-version=2025-06-01" -o none \
    || { echo "Project '$FOUNDRY_PROJECT' not found under '$FOUNDRY_ACCOUNT'"; exit 1; }

  SKU=$(az apim show -g "$APIM_RG" -n "$APIM_NAME" --query sku.name -o tsv)
  [[ "$SKU" != "Consumption" ]] || { echo "APIM Consumption tier doesn't support MCP servers/A2A. Use Developer, Basic(v2), Standard(v2) or Premium(v2)."; exit 1; }
  echo "    APIM tier: $SKU"
  MI=$(az apim show -g "$APIM_RG" -n "$APIM_NAME" --query identity.principalId -o tsv)
  if [[ -z "$MI" ]]; then
    echo "    Enabling system-assigned managed identity on APIM..."
    az apim update -g "$APIM_RG" -n "$APIM_NAME" --enable-managed-identity true -o none
  fi

  LOCATION="${LOCATION:-southeastasia}"
  az group create -n "$RG" -l "$LOCATION" "${GROUP_TAG_ARGS[@]}" -o none
  echo "==> Deploying demo resources + configuring existing Foundry/APIM..."
  OUT=$(az deployment group create -g "$RG" -n whisker-works-existing -f infra/existing.bicep \
    -p foundryAccountName="$FOUNDRY_ACCOUNT" foundryResourceGroup="$FOUNDRY_RG" projectName="$FOUNDRY_PROJECT" \
       apimName="$APIM_NAME" apimResourceGroup="$APIM_RG" deployerPrincipalId="$USER_ID" \
       createModelDeployments="${CREATE_MODEL_DEPLOYMENTS:-true}" \
       chatModelName="${CHAT_MODEL:-gpt-4.1-mini}" newModelName="${NEW_MODEL:-gpt-5-mini}" \
       connectFoundryAppInsights="${CONNECT_FOUNDRY_APP_INSIGHTS:-true}" \
       modelsApiPath="${MODELS_API_PATH:-models}" storeApiPath="${STORE_API_PATH:-store}" \
       configureGlobalApimDiagnostics="${GLOBAL_APIM_DIAGNOSTICS:-false}" \
    --query properties.outputs -o json)
else
  PUBLISHER_EMAIL="${PUBLISHER_EMAIL:?Set PUBLISHER_EMAIL}"
  LOCATION="${LOCATION:-southeastasia}"
  az group create -n "$RG" -l "$LOCATION" "${GROUP_TAG_ARGS[@]}" -o none
  echo "==> Deploying infrastructure (Foundry, APIM Basic v2, App Service, App Insights)..."
  OUT=$(az deployment group create -g "$RG" -n whisker-works -f infra/main.bicep \
    -p publisherEmail="$PUBLISHER_EMAIL" deployerPrincipalId="$USER_ID" \
    --query properties.outputs -o json)
fi
o() { echo "$OUT" | python3 -c "import json,sys; print(json.load(sys.stdin)['$1']['value'])"; }

PROJECT_ENDPOINT=$(o projectEndpoint)
APIM=$(o apimName)
APIM_RG_OUT=$(o apimResourceGroup)
GATEWAY=$(o apimGatewayUrl)
CATSTORE=$(o catstoreAppName)
A2A=$(o a2aAppName)
CHAT_MODEL_OUT=$(o chatModel)
NEW_MODEL_OUT=$(o newModel)

echo "==> Packaging and deploying web apps..."
mkdir -p .build
rm -f .build/catstore.zip .build/a2a.zip
(cd src/catstore-api && python3 -m zipfile -c ../../.build/catstore.zip main.py foundry_errors.py requirements.txt data static)
(cd src/a2a-agent && python3 -m zipfile -c ../../.build/a2a.zip main.py requirements.txt)
az webapp deploy -g "$RG" -n "$CATSTORE" --src-path .build/catstore.zip --type zip -o none
az webapp deploy -g "$RG" -n "$A2A" --src-path .build/a2a.zip --type zip -o none

echo "==> Reading APIM subscription keys..."
SUB_ID=$(az account show --query id -o tsv)
APIM_BASE="https://management.azure.com/subscriptions/$SUB_ID/resourceGroups/$APIM_RG_OUT/providers/Microsoft.ApiManagement/service/$APIM"
key() { az rest --method post --uri "$APIM_BASE/subscriptions/$1/listSecrets?api-version=$API_VERSION" --query primaryKey -o tsv; }
BRONZE_KEY=$(key whisker-demo-bronze)
GOLD_KEY=$(key whisker-demo-gold)

cat > agents/procode/.env <<EOF
FOUNDRY_PROJECT_ENDPOINT=$PROJECT_ENDPOINT
APIM_GATEWAY_URL=$GATEWAY
APIM_MODELS_PATH=${MODELS_API_PATH:-models}
APIM_STORE_PATH=${STORE_API_PATH:-store}
APIM_MCP_PATH=whisker-mcp
MCP_PROJECT_CONNECTION_NAME=
APIM_SUBSCRIPTION_KEY=$GOLD_KEY
APIM_BRONZE_KEY=$BRONZE_KEY
APIM_GOLD_KEY=$GOLD_KEY
CHAT_MODEL=$CHAT_MODEL_OUT
NEW_MODEL=$NEW_MODEL_OUT
AZURE_SUBSCRIPTION_ID=$SUB_ID
RG=$RG
APIM_NAME=$APIM
APIM_RG=$APIM_RG_OUT
EOF

echo
echo "Done. Summary:"
echo "  Foundry project endpoint : $PROJECT_ENDPOINT"
echo "  APIM gateway             : $GATEWAY"
echo "  Storefront               : $(o catstoreUrl)"
echo "  A2A agent card           : $(o a2aUrl)/.well-known/agent-card.json"
echo "  Local settings written   : agents/procode/.env (git-ignored)"
