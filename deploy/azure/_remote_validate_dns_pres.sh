#!/bin/bash
set +e
echo === DNS ===
resolvectl query apigateway-gen.qa.bsc.com.do 2>&1 | head -20
getent hosts apigateway-gen.qa.bsc.com.do || true
echo === CURL ===
curl -sk -m 20 -o /tmp/pres.json -w "HTTP=%{http_code} TIME=%{time_total}\n" \
  "https://apigateway-gen.qa.bsc.com.do/api/presentation/product/726588"
python3 - <<'PY' 2>/dev/null || head -c 200 /tmp/pres.json
import json
d=json.load(open("/tmp/pres.json"))
print("KEYS", list(d)[:10] if isinstance(d, dict) else type(d))
if isinstance(d, dict):
    print("isSucceded", d.get("isSucceded"))
    data=d.get("data")
    print("has_data", isinstance(data, dict))
    if isinstance(data, dict):
        prods=data.get("products")
        print("products", len(prods) if isinstance(prods, list) else None)
PY
echo
echo === ORCH CONTEXT ===
curl -sS -m 60 -X POST http://127.0.0.1:8447/orch/context \
  -H 'Content-Type: application/json' \
  -d '{"customer_id":"726588","conversation_id":"dns-check-1","allow_lab_fallback":false}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print({k:d.get(k) for k in ('status','context_source','products_count','active_count')}); print('detail', str(d.get('detail') or d.get('error') or '')[:300])"
