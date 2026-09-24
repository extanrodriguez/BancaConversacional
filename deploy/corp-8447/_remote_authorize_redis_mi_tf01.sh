#!/bin/bash
set -euo pipefail
NEW_OID='1849608a-68db-4122-93ee-800618849ad7'
OLD_OID='c0784572-03ae-4314-9ad0-311b1fafb710'
SUB='f2119315-95df-4c68-9f83-fb12c2ee0dfa'
RG='RG_BSC_PRJ_GENESIS'
NAME='bsc-cognitive-redis-qa'

TOK=$(curl -sS --max-time 5 -H Metadata:true \
  "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "TOKEN_OK len=${#TOK}"

curl -sS --max-time 30 -H "Authorization: Bearer ${TOK}" \
  "https://management.azure.com/subscriptions/${SUB}/resourceGroups/${RG}/resources?api-version=2021-04-01" \
  > /tmp/rg.json
python3 - <<'PY'
import json
d=json.load(open("/tmp/rg.json"))
print("RG_ERR", (d.get("error") or {}).get("code"), str((d.get("error") or {}).get("message",""))[:200])
for i in d.get("value") or []:
    n=i.get("name") or ""
    t=i.get("type") or ""
    if "redis" in n.lower() or "Redis" in t or "Cache" in t:
        print("RG_RES", t, "|", n, "|", i.get("id"))
PY

# Prefer redisEnterprise id if present
REDIS_ID=$(python3 - <<'PY'
import json
d=json.load(open("/tmp/rg.json"))
cands=[]
for i in d.get("value") or []:
    n=(i.get("name") or "").lower()
    t=i.get("type") or ""
    if "bsc-cognitive-redis-qa" in n:
        cands.append(i.get("id"))
print(cands[0] if cands else "")
PY
)
echo "REDIS_ID=${REDIS_ID}"

if [ -z "$REDIS_ID" ]; then
  echo "NO_REDIS_ID"
  exit 2
fi

# List role assignments on redis scope
curl -sS --max-time 30 -H "Authorization: Bearer ${TOK}" \
  "https://management.azure.com${REDIS_ID}/providers/Microsoft.Authorization/roleAssignments?api-version=2022-04-01" \
  > /tmp/ra_redis.json
python3 - <<PY
import json
d=json.load(open("/tmp/ra_redis.json"))
print("RA_ERR", (d.get("error") or {}).get("code"), str((d.get("error") or {}).get("message",""))[:220])
vals=d.get("value") or []
print("RA_COUNT", len(vals))
for i in vals:
    p=i.get("properties") or {}
    pid=p.get("principalId","")
    rid=(p.get("roleDefinitionId") or "")
    print("RA", pid, rid.split("/")[-1], "scope_tail", (p.get("scope") or "")[-50:])
PY

# Role definition names of interest
for ROLE_NAME in "Redis Cache Data Owner" "Redis Cache Data Contributor" "Data Owner"; do
  curl -sS --max-time 30 -H "Authorization: Bearer ${TOK}" \
    --get "https://management.azure.com/subscriptions/${SUB}/providers/Microsoft.Authorization/roleDefinitions" \
    --data-urlencode "api-version=2022-04-01" \
    --data-urlencode "\$filter=roleName eq '${ROLE_NAME}'" \
    > "/tmp/roledef_${ROLE_NAME// /_}.json" || true
done
python3 - <<'PY'
import json,glob
for f in sorted(glob.glob("/tmp/roledef_*.json")):
    d=json.load(open(f))
    vals=d.get("value") or []
    print("ROLEFILE", f, "count", len(vals), "err", (d.get("error") or {}).get("code"))
    for i in vals:
        print("  ", i.get("properties",{}).get("roleName"), i.get("name"), i.get("id","")[-70:])
PY

# Try create role assignment for NEW_OID with Redis Cache Data Owner if we find the def
ROLE_DEF=$(python3 - <<'PY'
import json,glob
prefer=["Redis Cache Data Owner","Redis Cache Data Contributor"]
found={}
for f in glob.glob("/tmp/roledef_*.json"):
    d=json.load(open(f))
    for i in d.get("value") or []:
        rn=(i.get("properties") or {}).get("roleName")
        if rn:
            found[rn]=i.get("id")
for p in prefer:
    if p in found:
        print(found[p]); break
PY
)
echo "ROLE_DEF=${ROLE_DEF}"

if [ -n "$ROLE_DEF" ]; then
  RA_NAME=$(python3 -c 'import uuid; print(uuid.uuid4())')
  BODY=$(python3 - <<PY
import json
print(json.dumps({
  "properties": {
    "roleDefinitionId": "${ROLE_DEF}",
    "principalId": "${NEW_OID}",
    "principalType": "ServicePrincipal"
  }
}))
PY
)
  echo "Creating role assignment ${RA_NAME} for NEW_OID ..."
  HTTP=$(curl -sS --max-time 60 -o /tmp/ra_create.json -w '%{http_code}' \
    -X PUT -H "Authorization: Bearer ${TOK}" -H "Content-Type: application/json" \
    -d "${BODY}" \
    "https://management.azure.com${REDIS_ID}/providers/Microsoft.Authorization/roleAssignments/${RA_NAME}?api-version=2022-04-01")
  echo "CREATE_HTTP=${HTTP}"
  python3 -c 'import json; d=json.load(open("/tmp/ra_create.json")); print("CREATE_BODY", {k:d.get(k) for k in ("id","name","error","properties") if k in d or True}); print(json.dumps(d,indent=2)[:800])'
else
  echo "NO_ROLE_DEF_FOUND"
fi
