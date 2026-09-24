import json
import urllib.request

BASE = "http://20.127.25.24:8447"


def post(path: str, body: dict, headers: dict | None = None) -> dict:
    h = {"Content-Type": "application/json", "ClientId": "CUST001"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers=h,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode())


def show(title: str, r: dict) -> None:
    reply = (r.get("client_response") or r.get("reply") or "")[:280].replace("\n", " | ")
    print("===", title)
    print("rag=", r.get("rag_status"), "status=", r.get("status"))
    steps = [t.get("step") for t in (r.get("decision_trace") or [])][:8]
    if steps:
        print("steps=", steps)
    print("reply=", reply)
    print()


# 1) Solo fecha límite del préstamo
r1 = post(
    "/inspect",
    {"question": "fecha limite de mi prestamo", "customer_id": "CUST001"},
)
show("fecha limite de mi prestamo", r1)

# 2) Hilo préstamo → fecha límite de pago (no glosario)
s = post("/orch/webhook/session", {})
cid = s.get("conversation_id")
print("cid", cid, "name", s.get("display_name") or (s.get("context") or {}).get("display_name"))
for q in [
    "cuando debo pagar mi prestamo en que fecha",
    "cual es la fecha limite de pago",
]:
    r = post("/orch/webhook/chat", {"message": q, "conversation_id": cid})
    show(q, r)
