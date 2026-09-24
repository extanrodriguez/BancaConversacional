import json
import urllib.request

BASE = "http://20.127.25.24:8447"


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "ClientId": "CUST001"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


for q in [
    "Compárame Multicrédito BSC con Cuotas BSC",
    "diferencia entre Multicrédito y Cuotas BSC",
]:
    r = post("/inspect", {"question": q, "customer_id": "CUST001"})
    print("===", q)
    print("status", r.get("status"), "rag", r.get("rag_status"))
    print("steps", [t.get("step") for t in (r.get("decision_trace") or [])][:10])
    print("reply", (r.get("client_response") or "")[:220].replace("\n", " "))
