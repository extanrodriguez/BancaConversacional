"""Probe T1 list vs T2 option selection latency on 8447."""
from __future__ import annotations

import json
import time
import uuid
from urllib.request import Request, urlopen

BASE = "http://20.127.25.24:8447"


def call(path: str, payload: dict):
    data = json.dumps(payload).encode()
    req = Request(BASE + path, data=data, headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.perf_counter()
    with urlopen(req, timeout=120) as r:
        body = json.loads(r.read().decode())
    return body, round((time.perf_counter() - t0) * 1000)


def main() -> None:
    html = urlopen(BASE + "/pruebas/", timeout=30).read().decode("utf-8", "replace")
    print(
        "ui",
        "Customer ID" in html,
        "docType" not in html,
        "app.js?v=7" in html,
    )

    cid = str(uuid.uuid4())
    login, _ = call(
        "/lab/login",
        {
            "customer_id": "TEST-QA-001",
            "conversation_id": cid,
            "portfolio": "qa_andres_david.json",
        },
    )
    print("login customer_id", login.get("customer_id"))

    r1, ms1 = call(
        "/turn",
        {
            "question": "dame un balance de mis cuentas",
            "customer_id": "TEST-QA-001",
            "conversation_id": cid,
        },
    )
    app1 = r1.get("app_channel") or {}
    opts = app1.get("options") or []
    print("T1", ms1, "ms", app1.get("status"))
    for o in opts:
        print(" opt", o.get("label"), o.get("ref"))

    opt = opts[0]
    ref = opt["ref"]
    label = opt["label"]
    digits = ref.split("_")[-1]
    if any(ch.isdigit() for ch in label):
        q = label
    else:
        q = f"{label.split('···')[0].strip()} terminada en {digits}"
    print("selection q=", q)

    r2, ms2 = call(
        "/turn",
        {
            "question": q,
            "customer_id": "TEST-QA-001",
            "conversation_id": cid,
        },
    )
    app2 = r2.get("app_channel") or {}
    trace0 = (r2.get("decision_trace") or [{}])[0]
    print(
        "T2",
        ms2,
        "ms",
        app2.get("status"),
        "inf",
        r2.get("inference_count"),
        "trace",
        trace0.get("step"),
    )
    print("reply", (app2.get("client_response") or r2.get("client_response") or "")[:220])
    print("audit", r2.get("audit"))


if __name__ == "__main__":
    main()
