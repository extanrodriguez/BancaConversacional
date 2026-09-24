#!/usr/bin/env bash
# Read-only validation.
# Run: bash scripts/azure_preflight.sh
# Do not run with `source`.

set -u

EXPECTED_TENANT="03e1b226-5789-4a97-90f6-44a44241ba6d"
EXPECTED_SUBSCRIPTION="871a5b90-0204-450e-b968-3190e9143faf"
EXPECTED_USER="boris.reina01@usa.edu.co"
EXPECTED_RG="rg-genesis-cognitive"
EXPECTED_PREFIX="/subscriptions/${EXPECTED_SUBSCRIPTION}/resourceGroups/${EXPECTED_RG}"

failed=0

actual_subscription="$(az account show --query id -o tsv 2>/dev/null || true)"
actual_tenant="$(az account show --query tenantId -o tsv 2>/dev/null || true)"
actual_user="$(az account show --query user.name -o tsv 2>/dev/null || true)"
actual_state="$(az account show --query state -o tsv 2>/dev/null || true)"

printf "%-22s %s\n" "User:" "$actual_user"
printf "%-22s %s\n" "Tenant:" "$actual_tenant"
printf "%-22s %s\n" "Subscription:" "$actual_subscription"
printf "%-22s %s\n" "State:" "$actual_state"

[[ "${actual_subscription,,}" == "${EXPECTED_SUBSCRIPTION,,}" ]] || failed=1
[[ "${actual_tenant,,}" == "${EXPECTED_TENANT,,}" ]] || failed=1
[[ "${actual_user,,}" == "${EXPECTED_USER,,}" ]] || failed=1
[[ "${actual_state,,}" == "enabled" ]] || failed=1

scope="/subscriptions/${EXPECTED_SUBSCRIPTION}"
owner_count="$(
  az role assignment list \
    --subscription "$EXPECTED_SUBSCRIPTION" \
    --assignee "$EXPECTED_USER" \
    --scope "$scope" \
    --include-inherited \
    --include-groups \
    --query "[?roleDefinitionName=='Owner'] | length(@)" \
    -o tsv 2>/dev/null || echo 0
)"
[[ "${owner_count:-0}" -ge 1 ]] || failed=1

rg_exists="$(
  az group exists \
    --subscription "$EXPECTED_SUBSCRIPTION" \
    --name "$EXPECTED_RG" 2>/dev/null || echo false
)"
[[ "$rg_exists" == "true" ]] || failed=1

resource_ids="$(
  az resource list \
    --subscription "$EXPECTED_SUBSCRIPTION" \
    --resource-group "$EXPECTED_RG" \
    --query "[].id" -o tsv 2>/dev/null || true
)"

resource_count=0
foreign_count=0
if [[ -n "$resource_ids" ]]; then
  while IFS= read -r resource_id; do
    [[ -z "$resource_id" ]] && continue
    resource_count=$((resource_count + 1))
    case "${resource_id,,}" in
      "${EXPECTED_PREFIX,,}"/*) ;;
      *) foreign_count=$((foreign_count + 1)) ;;
    esac
  done <<< "$resource_ids"
fi

printf "%-22s %s\n" "Owner assignments:" "$owner_count"
printf "%-22s %s\n" "Resource group exists:" "$rg_exists"
printf "%-22s %s\n" "Resources in group:" "$resource_count"
printf "%-22s %s\n" "Foreign resource IDs:" "$foreign_count"

[[ "$foreign_count" -eq 0 ]] || failed=1

if [[ "$failed" -eq 0 ]]; then
  echo "RESULT: PASS"
  exit 0
else
  echo "RESULT: FAIL"
  echo "No Azure write operation was executed."
  exit 1
fi
