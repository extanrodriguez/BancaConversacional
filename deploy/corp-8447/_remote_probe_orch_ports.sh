#!/bin/bash
set +e
echo === health ===
curl -sS -m 5 http://127.0.0.1:8080/health; echo
curl -sS -m 5 http://127.0.0.1:8000/health; echo
curl -sS -m 5 http://127.0.0.1:8080/api/version; echo
echo === who owns ports ===
ss -lntp | grep -E ':8000|:8080' || true
echo === processes ===
ps aux | grep -iE 'BancaConversacional|dotnet|genesis|uvicorn|gunicorn' | grep -v grep | head -20
echo === try chat front 8080 ===
curl -sS -m 20 -X POST http://127.0.0.1:8080/chat/front \
  -H 'Content-Type: application/json' \
  -d '{"question":"hola","customer_id":"726588","client_id":"726588","conversation_id":"probe-1","context_info":false}' \
  | head -c 400; echo
echo === try chat front 8000 ===
curl -sS -m 20 -X POST http://127.0.0.1:8000/chat/front \
  -H 'Content-Type: application/json' \
  -d '{"question":"hola","customer_id":"726588","client_id":"726588","conversation_id":"probe-1","context_info":false}' \
  | head -c 400; echo
echo === orch context with lab to confirm service ===
curl -sS -m 30 -X POST http://127.0.0.1:8447/orch/context \
  -H 'Content-Type: application/json' \
  -d '{"customer_id":"726588","conversation_id":"probe-lab","allow_lab_fallback":true}' \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print({k:d.get(k) for k in ('status','context_source','products_count','display_name')})"
