#!/bin/bash
set -euo pipefail
TOKEN=$(curl -sS --max-time 5 -H Metadata:true \
  "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
SUB=f2119315-95df-4c68-9f83-fb12c2ee0dfa
curl -sS --max-time 30 -X POST \
  -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
  -d "{\"subscriptions\":[\"${SUB}\"],\"query\":\"Resources | where name contains 'redis' or type contains 'redis' or type contains 'KeyVault' | project type,name,resourceGroup\"}" \
  "https://management.azure.com/providers/Microsoft.ResourceGraph/resources?api-version=2021-03-01" \
  > /tmp/arg.json
python3 - <<'PY'
import json
d=json.load(open("/tmp/arg.json"))
print("top_keys", sorted(d.keys()))
err=d.get("error") or {}
print("err", err.get("code"), (err.get("message") or "")[:200])
data=d.get("data")
if isinstance(data, dict):
  rows=data.get("rows") or []
  cols=[c.get("name") for c in (data.get("columns") or [])]
  print("cols", cols)
  for r in rows[:40]:
    print(r)
elif isinstance(data, list):
  print("list_len", len(data))
  for r in data[:40]:
    if isinstance(r, dict):
      print(r.get("type"), "|", r.get("name"), "|", r.get("resourceGroup"))
    else:
      print(r)
else:
  print("data_type", type(data), str(data)[:300])
PY
