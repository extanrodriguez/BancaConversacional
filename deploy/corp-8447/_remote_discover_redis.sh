#!/bin/bash
# Discover Azure Managed Redis resource via IMDS (no secrets printed).
set -euo pipefail
TOKEN=$(curl -sS --max-time 5 -H Metadata:true \
  "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
SUB=f2119315-95df-4c68-9f83-fb12c2ee0dfa
RG=RG_BSC_PRJ_GENESIS
NAME=bsc-cognitive-redis-qa

echo "=== list redis-like resources ==="
curl -sS --max-time 30 -H "Authorization: Bearer ${TOKEN}" \
  "https://management.azure.com/subscriptions/${SUB}/resourceGroups/${RG}/resources?api-version=2021-04-01" \
  > /tmp/az_rg_resources.json
python3 - <<'PY'
import json
d=json.load(open("/tmp/az_rg_resources.json"))
items=d.get("value", [])
for i in items:
    t=i.get("type","")
    n=i.get("name","")
    if any(x in (t+n).lower() for x in ("redis","cache")):
        print(t, "|", n, "|", i.get("id"))
print("TOTAL_RESOURCES", len(items))
if "error" in d:
    print("ERROR_OBJ", d.get("error",{}).get("code"), d.get("error",{}).get("message","")[:200])
PY

probe () {
  local url="$1"
  local code
  code=$(curl -sS --max-time 30 -o /tmp/azredis_probe.json -w "%{http_code}" -H "Authorization: Bearer ${TOKEN}" "$url" || echo ERR)
  echo "PROBE ${code} ${url}"
  python3 - <<'PY'
import json
try:
  d=json.load(open("/tmp/azredis_probe.json"))
except Exception as e:
  print("parse_fail", e); raise SystemExit
err=d.get("error") or {}
print("type=", d.get("type"), "name=", d.get("name"), "err=", err.get("code"), (err.get("message") or "")[:180])
if "properties" in d:
  props=d["properties"]
  print("prop_keys=", sorted(props.keys())[:30])
PY
}

probe "https://management.azure.com/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Cache/redisEnterprise/${NAME}?api-version=2024-03-01"
probe "https://management.azure.com/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Cache/Redis/${NAME}?api-version=2023-08-01"
# Azure Managed Redis might be Microsoft.Cache/redisEnterprise or a newer RP
probe "https://management.azure.com/subscriptions/${SUB}/resources?\$filter=name eq '${NAME}'&api-version=2021-04-01"
