#!/bin/bash
set +e
echo === internal bank ===
curl -sS -m 8 -o /dev/null -w "bank4430=%{http_code}\n" "http://172.27.4.20:4430/" || echo fail4430
curl -sS -m 8 -o /dev/null -w "bank4428=%{http_code}\n" "http://172.27.4.20:4428/" || echo fail4428
curl -sS -m 8 -o /dev/null -w "bank4429=%{http_code}\n" "http://172.27.4.20:4429/" || echo fail4429
echo === presentation paths ===
for u in \
  "http://172.27.4.20:4430/api/presentation/product/726588" \
  "http://172.27.4.20:4428/api/presentation/product/726588" \
  "http://172.27.4.20:4430/poc/api/presentation/product/726588" \
  "https://apigateway-gen.dev.bsc.com.do/api/presentation/product/726588"
do
  code=$(curl -sk -m 10 -o /tmp/p.json -w "%{http_code}" "$u" || echo ERR)
  echo "$code $u"
  head -c 160 /tmp/p.json 2>/dev/null; echo
done
echo === listen ===
ss -lntp 2>/dev/null | grep -E ':8000|:8080|:8446|:8447' || true
echo === dns ===
resolvectl query apigateway-gen.qa.bsc.com.do 2>&1 | head -8
resolvectl query apigateway-gen.dev.bsc.com.do 2>&1 | head -8
