"""Interfaz grafica de prueba: simula el App de banca conversacional.

Usa POST /turn (API de produccion). Opcionalmente POST /inspect para ver la traza.
"""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from client import DEFAULT_ENDPOINT, CognitiveClient

ROOT = Path(__file__).resolve().parent
PREGUNTAS_PATH = ROOT / "mvp_preguntas.json"
PORTFOLIOS_DIR = ROOT.parent / "Test_local" / "data" / "portfolios"


def _load_casos() -> list[dict]:
    if not PREGUNTAS_PATH.exists():
        return []
    data = json.loads(PREGUNTAS_PATH.read_text(encoding="utf-8"))
    return data.get("casos", [])


def _portfolio_names() -> list[str]:
    if not PORTFOLIOS_DIR.exists():
        return []
    return sorted(p.name for p in PORTFOLIOS_DIR.glob("*.json"))


class BancaPruebaApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Genesis — Simulador App Banca Conversacional")
        self.root.geometry("1280x780")
        self.root.minsize(1020, 640)

        self.client = CognitiveClient(DEFAULT_ENDPOINT)
        self.casos = _load_casos()
        self.conversation_id = str(uuid.uuid4())
        self._busy = False

        self._build()
        self.root.after(200, self._ping)

    def _build(self) -> None:
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")

        ttk.Label(top, text="API").pack(side="left")
        self.url_var = tk.StringVar(value=DEFAULT_ENDPOINT)
        ttk.Entry(top, textvariable=self.url_var, width=36).pack(side="left", padx=6)

        ttk.Button(top, text="Probar conexion", command=self._ping).pack(side="left")
        self.health_var = tk.StringVar(value="sin conexion")
        ttk.Label(top, textvariable=self.health_var).pack(side="left", padx=10)

        ttk.Label(top, text="Cliente").pack(side="left")
        self.customer_var = tk.StringVar(value="CUST001")
        self.customer_combo = ttk.Combobox(
            top, textvariable=self.customer_var, width=14, state="readonly",
            values=("CUST001", "CUST002", "CUST003"),
        )
        self.customer_combo.pack(side="left", padx=6)

        ttk.Label(top, text="Modo").pack(side="left")
        self.mode_var = tk.StringVar(value="App (/turn)")
        ttk.Combobox(
            top, textvariable=self.mode_var, width=18, state="readonly",
            values=("App (/turn)", "Laboratorio (/inspect)"),
        ).pack(side="left", padx=6)

        self.force_core_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="force_core_query", variable=self.force_core_var).pack(side="left", padx=8)
        ttk.Label(top, text="Portafolio").pack(side="left")
        names = _portfolio_names() or ["(sin Test_local)"]
        self.portfolio_var = tk.StringVar(value="core_real_sample.json" if "core_real_sample.json" in names else names[0])
        ttk.Combobox(top, textvariable=self.portfolio_var, width=28, state="readonly", values=names).pack(side="left", padx=4)
        ttk.Button(top, text="Cargar Core", command=self._load_portfolio).pack(side="left")
        ttk.Button(top, text="Nueva sesion", command=self._new_session).pack(side="right")

        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        left = ttk.Frame(body, padding=4)
        center = ttk.Frame(body, padding=4)
        right = ttk.Frame(body, padding=4)
        body.add(left, weight=1)
        body.add(center, weight=3)
        body.add(right, weight=2)

        self._build_catalog(left)
        self._build_chat(center)
        self._build_debug(right)

    def _build_catalog(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Preguntas MVP (Excel)", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        productos = sorted({c.get("producto") or "Sin producto" for c in self.casos})
        self.producto_var = tk.StringVar(value="Todos")
        combo = ttk.Combobox(
            parent, textvariable=self.producto_var, state="readonly",
            values=["Todos", *productos],
        )
        combo.pack(fill="x", pady=4)
        combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_casos())

        cols = ("id", "intencion")
        self.casos_tree = ttk.Treeview(parent, columns=cols, show="headings", height=12)
        self.casos_tree.heading("id", text="#")
        self.casos_tree.heading("intencion", text="Intencion")
        self.casos_tree.column("id", width=36, stretch=False)
        self.casos_tree.column("intencion", width=220)
        self.casos_tree.pack(fill="both", expand=True)
        self.casos_tree.bind("<<TreeviewSelect>>", lambda _e: self._on_caso())

        ttk.Label(parent, text="Expresiones del cliente").pack(anchor="w", pady=(8, 2))
        self.expr_list = tk.Listbox(parent, height=8)
        self.expr_list.pack(fill="both", expand=True)
        self.expr_list.bind("<Double-Button-1>", lambda _e: self._send_selected_expr())
        ttk.Button(parent, text="Enviar expresion seleccionada", command=self._send_selected_expr).pack(
            fill="x", pady=6
        )

        ttk.Label(parent, text="Respuesta esperada (negocio)").pack(anchor="w")
        self.expected_txt = tk.Text(parent, height=6, wrap="word", state="disabled")
        self.expected_txt.pack(fill="x")
        self._refresh_casos()

    def _build_chat(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Chat (simula el App)", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.session_var = tk.StringVar(value=f"sesion {self.conversation_id[:8]}…")
        ttk.Label(parent, textvariable=self.session_var, foreground="#555").pack(anchor="w")

        self.chat = tk.Text(parent, wrap="word", state="disabled", bg="#f6f7f9")
        self.chat.pack(fill="both", expand=True, pady=4)
        self.chat.tag_configure("user", foreground="#0b3d91", lmargin1=8, lmargin2=8, rmargin=40, spacing3=8)
        self.chat.tag_configure("bot", foreground="#163a2a", lmargin1=40, lmargin2=40, rmargin=8, spacing3=8)
        self.chat.tag_configure("meta", foreground="#777", font=("Segoe UI", 8), spacing3=6)
        self.chat.tag_configure("err", foreground="#a40000", lmargin1=40, rmargin=8)

        row = ttk.Frame(parent)
        row.pack(fill="x")
        self.input_var = tk.StringVar()
        entry = ttk.Entry(row, textvariable=self.input_var)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        entry.bind("<Return>", lambda _e: self._send())
        ttk.Button(row, text="Enviar", command=self._send).pack(side="right")

    def _build_debug(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Diagnostico del turno", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.debug_summary = tk.Text(parent, height=8, wrap="word", state="disabled")
        self.debug_summary.pack(fill="x", pady=4)
        ttk.Label(parent, text="JSON crudo").pack(anchor="w")
        self.debug_json = tk.Text(parent, wrap="none", state="disabled")
        self.debug_json.pack(fill="both", expand=True)

    def _refresh_casos(self) -> None:
        self.casos_tree.delete(*self.casos_tree.get_children())
        filtro = self.producto_var.get()
        for caso in self.casos:
            if filtro != "Todos" and (caso.get("producto") or "Sin producto") != filtro:
                continue
            self.casos_tree.insert(
                "", "end",
                iid=str(caso["id"]),
                values=(caso["id"], (caso.get("intencion") or "")[:80]),
            )

    def _selected_caso(self) -> dict | None:
        sel = self.casos_tree.selection()
        if not sel:
            return None
        cid = int(sel[0])
        return next((c for c in self.casos if c["id"] == cid), None)

    def _on_caso(self) -> None:
        caso = self._selected_caso()
        self.expr_list.delete(0, "end")
        self._set_text(self.expected_txt, "")
        if not caso:
            return
        for expr in caso.get("expresiones") or []:
            self.expr_list.insert("end", expr)
        esperado = caso.get("respuesta_esperada") or caso.get("respuesta_patron") or ""
        extra = []
        if caso.get("dato_objetivo"):
            extra.append(f"Dato: {caso['dato_objetivo']}")
        if caso.get("elementos_prohibidos"):
            extra.append(f"Prohibido: {caso['elementos_prohibidos']}")
        if extra:
            esperado = esperado + "\n\n" + "\n".join(extra)
        self._set_text(self.expected_txt, esperado)
        if caso.get("expresiones"):
            self.expr_list.selection_set(0)

    def _send_selected_expr(self) -> None:
        sel = self.expr_list.curselection()
        if not sel:
            return
        self.input_var.set(self.expr_list.get(sel[0]))
        self._send()

    def _new_session(self) -> None:
        self.conversation_id = str(uuid.uuid4())
        self.session_var.set(f"sesion {self.conversation_id[:8]}…")
        self._set_text(self.chat, "", disabled=True)
        self._set_text(self.debug_summary, "")
        self._set_text(self.debug_json, "")
        self._append_chat("Nueva sesion. El contexto de producto anterior se borro.", "meta")

    def _load_portfolio(self) -> None:
        name = self.portfolio_var.get()
        path = PORTFOLIOS_DIR / name
        if not path.exists():
            messagebox.showerror("Portafolio", f"No existe {path}")
            return
        envelope = json.loads(path.read_text(encoding="utf-8"))
        products = envelope.get("data") if isinstance(envelope.get("data"), list) else envelope.get("products") or []
        context_data = {
            "primerNombre": envelope.get("primerNombre") or "Cliente",
            "products": products,
        }
        self.client = CognitiveClient(self.url_var.get().strip())
        customer_id = self.customer_var.get()
        conversation_id = self.conversation_id

        def work() -> None:
            try:
                data = self.client.turn(
                    None,
                    customer_id=customer_id,
                    conversation_id=conversation_id,
                    context_info=True,
                    context_op="load",
                    context={"data": context_data},
                )
                self.root.after(0, lambda: self._append_chat(
                    f"Portafolio {name} cargado: {data.get('status')} · {data.get('products_count')} productos",
                    "meta",
                ))
            except Exception as exc:
                err = str(exc)
                self.root.after(0, lambda: self._append_chat(err, "err"))

        threading.Thread(target=work, daemon=True).start()

    def _ping(self) -> None:
        self.client = CognitiveClient(self.url_var.get().strip())
        self.health_var.set("probando…")

        def work() -> None:
            try:
                health = self.client.health()
                customers = self.client.customers()
                msg = f"ok · {health.get('service')} · env={health.get('env')} · puerto remoto listo"
                ids = [c.get("customer_id") for c in customers if c.get("customer_id")]
                self.root.after(0, lambda: self._on_ping_ok(msg, ids))
            except Exception as exc:
                err = str(exc)
                self.root.after(0, lambda: self.health_var.set(f"error: {err[:80]}"))

        threading.Thread(target=work, daemon=True).start()

    def _on_ping_ok(self, msg: str, customer_ids: list[str]) -> None:
        self.health_var.set(msg)
        if customer_ids:
            self.customer_combo["values"] = customer_ids
            if self.customer_var.get() not in customer_ids:
                self.customer_var.set(customer_ids[0])

    def _send(self) -> None:
        question = self.input_var.get().strip()
        if not question or self._busy:
            return
        self._busy = True
        self.input_var.set("")
        self._append_chat(question, "user")
        self._append_chat("pensando…", "meta")
        self.client = CognitiveClient(self.url_var.get().strip())
        customer_id = self.customer_var.get()
        conversation_id = self.conversation_id
        lab = self.mode_var.get().startswith("Laboratorio")
        force_core = self.force_core_var.get()

        def work() -> None:
            try:
                if lab:
                    data = self.client.inspect(
                        question, customer_id=customer_id, conversation_id=conversation_id
                    )
                else:
                    data = self.client.turn(
                        question,
                        customer_id=customer_id,
                        conversation_id=conversation_id,
                        force_core_query=force_core,
                    )
                self.root.after(0, lambda: self._on_reply(data, lab))
            except Exception as exc:
                err = str(exc)
                self.root.after(0, lambda: self._on_error(err))

        threading.Thread(target=work, daemon=True).start()

    def _on_reply(self, data: dict, lab: bool) -> None:
        self._busy = False
        self._drop_last_meta()
        if lab:
            text = data.get("client_response") or data.get("status") or "(sin respuesta)"
            summary = self._summarize_inspect(data)
        else:
            app_ch = data.get("app_channel") or {}
            text = app_ch.get("client_response") or app_ch.get("status") or "(sin respuesta)"
            if app_ch.get("options"):
                opts = " | ".join(o.get("label") or o.get("ref") or "?" for o in app_ch["options"])
                text = f"{text}\nOpciones: {opts}"
            summary = self._summarize_turn(data)
        self._append_chat(str(text), "bot")
        self._set_text(self.debug_summary, summary)
        self._set_text(self.debug_json, json.dumps(data, ensure_ascii=False, indent=2))

    def _on_error(self, err: str) -> None:
        self._busy = False
        self._drop_last_meta()
        self._append_chat(err, "err")
        self._set_text(self.debug_summary, err)

    def _summarize_turn(self, data: dict) -> str:
        app_ch = data.get("app_channel") or {}
        audit = data.get("audit") or {}
        core = data.get("core_channel")
        lines = [
            f"status: {app_ch.get('status')}",
            f"intent_id: {app_ch.get('intent_id')}",
            f"account_ref: {app_ch.get('account_ref')}",
            f"turn: {app_ch.get('turn_number')}",
            f"latencia: {audit.get('total_ms')} ms · slowest={audit.get('slowest_step')}",
            f"rag: {audit.get('rag_status')}",
            f"core_channel: {'SI (contrato 1.2)' if core else 'null'}",
        ]
        return "\n".join(lines)

    def _summarize_inspect(self, data: dict) -> str:
        actions = data.get("actions") or []
        a0 = actions[0] if actions else {}
        ents = a0.get("detected_entities") or {}
        lines = [
            f"status: {data.get('status')}",
            f"intent_id: {a0.get('intent_id')}",
            f"capability: {a0.get('capability_id') or a0.get('capability_candidate')}",
            f"account_ref: {ents.get('account_ref')}",
            f"client_response: {(data.get('client_response') or '')[:160]}",
            f"loan_detail: {json.dumps(data.get('loan_detail'), ensure_ascii=False) if data.get('loan_detail') else 'null'}",
        ]
        return "\n".join(lines)

    def _append_chat(self, text: str, tag: str) -> None:
        self.chat.configure(state="normal")
        prefix = {"user": "Tu: ", "bot": "Genesis: ", "meta": "", "err": "Error: "}.get(tag, "")
        self.chat.insert("end", f"{prefix}{text}\n", tag)
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def _drop_last_meta(self) -> None:
        self.chat.configure(state="normal")
        # remove last "pensando…" line if present
        last = self.chat.get("end-2l", "end-1l")
        if "pensando" in last:
            self.chat.delete("end-2l", "end-1l")
        self.chat.configure(state="disabled")

    @staticmethod
    def _set_text(widget: tk.Text, value: str, disabled: bool = True) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        if value:
            widget.insert("1.0", value)
        if disabled:
            widget.configure(state="disabled")


def main() -> None:
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    BancaPruebaApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
