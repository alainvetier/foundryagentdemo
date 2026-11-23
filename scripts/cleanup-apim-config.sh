#!/usr/bin/env bash
# Removes everything the demo added to a SHARED/EXISTING APIM instance and Foundry project
# (use with the "existing resources" setup). The demo resource group is removed separately with cleanup.sh.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source agents/procode/.env; set +a
APIM_RG="${APIM_RG:-$RG}"

echo "This removes from APIM '$APIM_NAME': whisker-* APIs, MCP servers, products (and their subscriptions), backends, logger."
read -r -p "Continue? [y/N] " answer
[[ "$answer" == "y" ]] || exit 0

API_VERSION="2025-09-01-preview"
SUB_ID=$(az account show --query id -o tsv)
BASE="https://management.azure.com/subscriptions/$SUB_ID/resourceGroups/$APIM_RG/providers/Microsoft.ApiManagement/service/$APIM_NAME"
del() { az rest --method delete --uri "$BASE/$1?api-version=$API_VERSION" --headers "If-Match=*" -o none 2>/dev/null && echo "  - $1" || true; }

# MCP servers first (their tools reference the store API operations)
for api in whisker-mcp whisker-mcp-live whisker-mcp-orders learn-mcp wellness-agent; do del "apis/$api"; done
for api in whisker-works-api whisker-foundry-models foundry-models; do del "apis/$api"; done
for product in whisker-bronze whisker-gold; do
  az apim product delete -g "$APIM_RG" -n "$APIM_NAME" --product-id "$product" --delete-subscriptions true --yes -o none 2>/dev/null && echo "  - products/$product" || true
done
for backend in whisker-foundry-models whisker-content-safety; do del "backends/$backend"; done
del "loggers/whisker-appinsights-logger"

echo
echo "APIM cleaned. Not removed automatically (shared resources):"
echo "  - Foundry model deployments ($CHAT_MODEL, $NEW_MODEL) and agents (whiskers-*, kernel-panic-ops)"
echo "  - Role assignments granted to APIM / the storefront app / you on the Foundry account"
echo "  - The A2A API if you imported it under a different name than 'wellness-agent'"
