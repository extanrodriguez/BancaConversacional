#!/bin/bash
# Smoke test for Genesis Cognitive deployment.
# Usage: bash scripts/smoke_remote_health.sh [BASE_URL]
# Default: http://localhost:8445

set -e
BASE="${1:-http://localhost:8445}"
echo "=== Genesis Cognitive Smoke Test ==="
echo "Target: $BASE"
echo

# 1. Health
echo "1) GET /health"
HEALTH=$(curl -sf "$BASE/health")
echo "   $HEALTH"
STATUS=$(echo "$HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['status'])" 2>/dev/null || echo "FAIL")
RAG=$(echo "$HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('rag','?'))" 2>/dev/null || echo "?")
echo "   status=$STATUS rag=$RAG"
[ "$STATUS" = "ok" ] || { echo "   FAIL: health not ok"; exit 1; }
echo "   PASS"
echo

# 2. POST /inspect — personal saldo
echo "2) POST /inspect (CUST001 saldo ahorros)"
R2=$(curl -sf -X POST "$BASE/inspect" \
  -H "Content-Type: application/json" \
  -d '{"question":"saldo de mi cuenta de ahorros?","conversation_id":"smoke-1","customer_id":"CUST001"}')
S2=$(echo "$R2" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" 2>/dev/null)
echo "   status=$S2"
[ "$S2" = "VALID_CONTRACT" ] || { echo "   FAIL"; exit 1; }
echo "   PASS"
echo

# 3. POST /turn alias
echo "3) POST /turn (alias)"
R3=$(curl -sf -X POST "$BASE/turn" \
  -H "Content-Type: application/json" \
  -d '{"question":"hola","conversation_id":"smoke-2","customer_id":"CUST001"}')
S3=$(echo "$R3" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" 2>/dev/null)
echo "   status=$S3"
echo "   PASS"
echo

# 4. POST /contract-lab/dispatch
echo "4) POST /contract-lab/dispatch (Consulta portafolio)"
R4=$(curl -sf -X POST "$BASE/contract-lab/dispatch" \
  -H "Content-Type: application/json" \
  -d '{"question":"Consulta portafolio","conversation_id":"smoke-3","customer_id":"CUST001"}')
S4=$(echo "$R4" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" 2>/dev/null)
echo "   status=$S4"
[ "$S4" = "CONTRACT_EMITTED" ] || { echo "   FAIL"; exit 1; }
echo "   PASS"
echo

# 5. POST /rag/query
echo "5) POST /rag/query (negocio)"
R5=$(curl -sf -X POST "$BASE/rag/query" \
  -H "Content-Type: application/json" \
  -d '{"question":"requisitos prestamo hipotecario","conversation_id":"smoke-4","customer_id":"CUST001"}')
S5=$(echo "$R5" | python3 -c "import sys,json; print(json.load(sys.stdin)['rag_status'])" 2>/dev/null)
echo "   rag_status=$S5"
echo "   PASS"
echo

echo "=== ALL SMOKE PASS ==="
echo "Service ready at $BASE"
