import json
import urllib.request

BASE = "http://20.127.25.24:8447"


def post(path: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json", "ClientId": "CUST001"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def main() -> None:
    s = post("/orch/webhook/session", {})
    cid = s.get("conversation_id")
    print("cid", cid)
    turns = [
        "Que es Multicredito?",
        "cual es el consumo minimo?",
        "se puede hacer avance de efectivo",
        "que comisiones tiene el avance",
        "que hago si me roban el plastico",
    ]
    for q in turns:
        r = post("/orch/webhook/chat", {"message": q, "conversation_id": cid})
        reply = (r.get("reply") or r.get("client_response") or "").replace("\n", " ")
        print("---", q)
        print("rag=", r.get("rag_status"), "reply=", reply[:180])

    print("\n=== CC01 alt ===")
    s = post("/orch/webhook/session", {})
    cid = s.get("conversation_id")
    for q in [
        "diferencia entre Multicredito y Cuotas BSC",
        "que los distingue",
        "como se pagan en cada uno",
    ]:
        r = post("/orch/webhook/chat", {"message": q, "conversation_id": cid})
        reply = (r.get("reply") or r.get("client_response") or "").replace("\n", " ")
        print("---", q)
        print("rag=", r.get("rag_status"), "reply=", reply[:180])


if __name__ == "__main__":
    main()
