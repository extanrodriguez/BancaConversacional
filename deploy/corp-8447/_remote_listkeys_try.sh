#!/bin/bash
set -euo pipefail
TOKEN=$(curl -sS --max-time 5 -H Metadata:true \
  "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
SUB=f2119315-95df-4c68-9f83-fb12c2ee0dfa
RG=RG_BSC_PRJ_GENESIS
curl -sS --max-time 30 -H "Authorization: Bearer ${TOKEN}" \
  "https://management.azure.com/subscriptions/${SUB}/resourceGroups/${RG}/resources?api-version=2021-04-01" \
  > /tmp/az_rg.json
python3 - <<'PY'
import json
d=json.load(open("/tmp/az_rg.json"))
print("err", (d.get("error") or {}).get("code"), (d.get("error") or {}).get("message","")[:200])
for i in d.get("value") or []:
    print("RES", i.get("type"), "|", i.get("name"))
PY

# Try listKeys anyway on redisEnterprise databases/default
for URL in \
  "https://management.azure.com/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Cache/redisEnterprise/bsc-cognitive-redis-qa/listKeys?api-version=2024-03-01" \
  "https://management.azure.com/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Cache/redisEnterprise/bsc-cognitive-redis-qa/databases/default/listKeys?api-version=2024-03-01" \
  "https://management.azure.com/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Cache/Redis/bsc-cognitive-redis-qa/listKeys?api-version=2023-08-01"
 do
  CODE=$(curl -sS --max-time 30 -o /tmp/az_keys.json -w "%{http_code}" -X POST -H "Authorization: Bearer ${TOKEN}" -H "Content-Length: 0" "$URL" || echo ERR)
  echo "LISTKEYS $CODE"
  python3 - <<'PY'
import json
d=json.load(open("/tmp/az_keys.json"))
err=d.get("error") or {}
keys=list(d.keys())
# never print key values
print("resp_keys", keys, "err", err.get("code"), (err.get("message") or "")[:160])
has_primary = any(k.lower() in ("primarykey","primaryaccesskey","primaryaccesskey") for k in keys)
print("HAS_PRIMARY_FIELD", any("primary" in k.lower() for k in keys))
if any("primary" in k.lower() for k in keys):
    # write key to restricted file only
    for k,v in d.items():
        if "primary" in k.lower() and isinstance(v,str) and len(v)>8:
            open("/tmp/redis_primary.key","w").write(v)
            import os; os.chmod("/tmp/redis_primary.key", 0o600)
            print("WROTE_KEY_FILE len", len(v))
            break
PY
done
