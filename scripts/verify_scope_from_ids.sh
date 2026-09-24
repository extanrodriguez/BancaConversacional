#!/usr/bin/env bash
# Validate resource IDs from stdin.
# Example:
# cat planned-resource-ids.txt | bash scripts/verify_scope_from_ids.sh

set -u

EXPECTED_PREFIX="/subscriptions/871a5b90-0204-450e-b968-3190e9143faf/resourceGroups/rg-genesis-cognitive/"
failed=0
count=0

while IFS= read -r resource_id; do
  [[ -z "$resource_id" ]] && continue
  count=$((count + 1))
  case "${resource_id,,}" in
    "${EXPECTED_PREFIX,,}"*) ;;
    *)
      echo "OUT OF SCOPE: $resource_id"
      failed=1
      ;;
  esac
done

echo "IDs checked: $count"

if [[ "$failed" -eq 0 ]]; then
  echo "RESULT: PASS"
  exit 0
else
  echo "RESULT: FAIL"
  exit 1
fi
