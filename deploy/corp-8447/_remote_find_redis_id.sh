#!/bin/bash
set -euo pipefail
SUB='f2119315-95df-4c68-9f83-fb12c2ee0dfa'
RG='RG_BSC_PRJ_GENESIS'
NAME='bsc-cognitive-redis-qa'
TOK=$(curl -sS --max-time 5 -H Metadata:true \
  "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo "=== try known resource id patterns ==="
for PATHID in \
  "/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Cache/redisEnterprise/${NAME}" \
  "/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Cache/Redis/${NAME}" \
  "/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Cache/redisEnterprise/${NAME}/databases/default"
do
  CODE=$(curl -sS --max-time 20 -o /tmp/resprobe.json -w '%{http_code}' \
    -H "Authorization: Bearer ${TOK}" \
    "https://management.azure.com${PATHID}?api-version=2024-03-01" || echo ERR)
  echo "PROBE ${CODE} ${PATHID}"
  python3 -c 'import json; d=json.load(open("/tmp/resprobe.json")); print(" ", (d.get("type") or d.get("error",{}).get("code")), (d.get("name") or d.get("error",{}).get("message","")[:120]))' 2>/dev/null || true
done

# Also 2025 api for managed redis
for API in 2024-03-01 2024-11-01-preview 2025-05-01-preview; do
  CODE=$(curl -sS --max-time 20 -o /tmp/resprobe.json -w '%{http_code}' \
    -H "Authorization: Bearer ${TOK}" \
    "https://management.azure.com/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Cache/redisEnterprise/${NAME}?api-version=${API}" || echo ERR)
  echo "API ${API} -> ${CODE}"
done

# az if present
if command -v az >/dev/null; then
  echo "=== az identity ==="
  az account show --query '{name:name,id:id,user:user.name}' -o json 2>/dev/null || echo AZ_NOT_LOGGED
  az redis list -g "$RG" -o table 2>/dev/null | head -20 || true
  az redisenterprise list -g "$RG" -o table 2>/dev/null | head -20 || true
  az resource list -g "$RG" --query "[?contains(name, 'redis')].{name:name,type:type,id:id}" -o json 2>/dev/null | head -c 2000 || true
fi

# RG list summary
curl -sS --max-time 30 -H "Authorization: Bearer ${TOK}" \
  "https://management.azure.com/subscriptions/${SUB}/resourceGroups/${RG}/resources?api-version=2021-04-01" \
  > /tmp/rg.json
python3 - <<'PY'
import json
d=json.load(open("/tmp/rg.json"))
print("keys", list(d.keys()))
print("err", d.get("error"))
vals=d.get("value") or []
print("count", len(vals))
for i in vals[:30]:
    print("-", i.get("type"), i.get("name"))
PY
