#!/usr/bin/env bash
# Deletes the demo resource group, then purges the soft-deleted Foundry account so the name can be reused.
set -euo pipefail
RG="${RG:-rg-whisker-works}"
read -r -p "Delete resource group '$RG' and everything in it? [y/N] " answer
[[ "$answer" == "y" ]] || exit 0

FOUNDRY=$(az cognitiveservices account list -g "$RG" --query "[0].name" -o tsv || true)
LOCATION=$(az group show -n "$RG" --query location -o tsv)
az group delete -n "$RG" --yes
if [[ -n "$FOUNDRY" ]]; then
  az cognitiveservices account purge -g "$RG" -n "$FOUNDRY" -l "$LOCATION" || true
fi
echo "Cleaned up."
