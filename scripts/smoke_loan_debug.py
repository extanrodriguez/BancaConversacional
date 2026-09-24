"""Debug: run the resolver directly to see where it fails."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

async def main():
    import httpx
    import uuid
    import json

    # Hit endpoint but capture the full error path
    cid = str(uuid.uuid4())
    r = httpx.post("http://localhost:8000/inspect", json={
        "question": "Cuanto es la cuota de mi prestamo",
        "customer_id": "CUST002",
        "conversation_id": cid,
    }, timeout=60)
    d = r.json()
    print("HTTP:", r.status_code)
    print("status:", d.get("status"))
    print("error_detail:", d.get("error_detail"))

    # Now try with slightly different phrasing
    cid2 = str(uuid.uuid4())
    r2 = httpx.post("http://localhost:8000/inspect", json={
        "question": "Quiero saber la cuota mensual de mi credito",
        "customer_id": "CUST002",
        "conversation_id": cid2,
    }, timeout=60)
    d2 = r2.json()
    print("\nHTTP:", r2.status_code)
    print("status:", d2.get("status"))
    print("error_detail:", d2.get("error_detail"))
    if d2.get("actions"):
        a = d2["actions"][0]
        print("intent:", a.get("intent_id"))
        print("acct:", a.get("detected_entities", {}).get("account_ref"))

asyncio.run(main())
