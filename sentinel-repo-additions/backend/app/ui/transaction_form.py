"""Tkinter client: Transaction Entry + Live Dashboard + High-Risk Queue/Feedback. Talks to the backend only via TCP (submit) and
REST (read), so a slow/closed UI can never block scoring.   Run:  python -m app.ui.transaction_form"""
import json
import threading
import tkinter as tk
import urllib.request
import uuid
from datetime import datetime, timezone
from tkinter import messagebox, simpledialog, ttk

from app.config import settings
from app.transport.tcp_client import send_transaction

API = f"http://{settings.API_HOST}:{settings.API_PORT}"
FIELDS = [("transaction_id", ""), ("user_id", "C0001234"), ("amount", "2500"), ("currency", "INR"), ("merchant_id", "M101"),
          ("merchant_category", "grocery"), ("device_id", "dev-aaa111"), ("ip_address", "49.12.34.56"), ("country", "IN"),
          ("city", "Chennai"), ("channel", "web")]
COLORS = {"LOW": "#34d399", "MEDIUM": "#fbbf24", "HIGH": "#f87171"}


def api(path, data=None):
    req = urllib.request.Request(API + path, data=json.dumps(data).encode() if data else None, headers={"Content-Type": "application/json", "X-API-Key": settings.API_KEY})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Real-Time Transaction Risk Scoring")
        self.geometry("1100x640")
        nb = ttk.Notebook(self); nb.pack(fill="both", expand=True)
        self.entry_tab, self.dash_tab, self.queue_tab = ttk.Frame(nb), ttk.Frame(nb), ttk.Frame(nb)
        nb.add(self.entry_tab, text="Transaction Entry"); nb.add(self.dash_tab, text="Live Dashboard"); nb.add(self.queue_tab, text="High-Risk Queue")
        self._entry(); self._dash(); self._queue(); self.after(500, self.refresh)

    def _entry(self):
        self.vars = {}
        for i, (k, d) in enumerate(FIELDS):
            ttk.Label(self.entry_tab, text=k).grid(row=i, column=0, sticky="w", padx=12, pady=3)
            self.vars[k] = tk.StringVar(value=d)
            ttk.Entry(self.entry_tab, textvariable=self.vars[k], width=36).grid(row=i, column=1, pady=3)
        ttk.Button(self.entry_tab, text="Submit transaction", command=self.submit).grid(row=len(FIELDS), column=1, pady=12, sticky="w")
        self.result = ttk.Label(self.entry_tab, text="", font=("Segoe UI", 12, "bold")); self.result.grid(row=len(FIELDS) + 1, column=0, columnspan=2, padx=12, sticky="w")

    def submit(self):
        txn = {k: v.get().strip() for k, v in self.vars.items() if v.get().strip()}
        txn["transaction_id"] = txn.get("transaction_id") or "T" + uuid.uuid4().hex[:12]
        try:
            txn["amount"] = float(txn.get("amount", ""))
        except ValueError:
            return messagebox.showerror("Invalid", "amount must be a number")
        txn["event_time"] = datetime.now(timezone.utc).isoformat()
        def run():
            try:
                r = send_transaction(txn)
                self.after(0, lambda: self.result.config(text=f"{r['status']}  {r.get('event_id', '')}  {'; '.join(r.get('errors', []))}"))
            except OSError as e:
                self.after(0, lambda: self.result.config(text=f"Cannot reach backend: {e}"))
        threading.Thread(target=run, daemon=True).start()   # network I/O never blocks the UI thread

    def _dash(self):
        self.kpi = ttk.Label(self.dash_tab, text="...", font=("Segoe UI", 12)); self.kpi.pack(anchor="w", padx=10, pady=8)
        cols = ("event_id", "amount", "merchant_id", "city", "risk_score", "risk_category", "decision", "latency_ms")
        self.tree = ttk.Treeview(self.dash_tab, columns=cols, show="headings", height=18)
        for c in cols: self.tree.heading(c, text=c); self.tree.column(c, width=120)
        for k, v in COLORS.items(): self.tree.tag_configure(k, foreground=v)
        self.tree.pack(fill="both", expand=True, padx=10)
        self.tree.bind("<<TreeviewSelect>>", self.show_detail)
        self.detail = tk.Text(self.dash_tab, height=7); self.detail.pack(fill="x", padx=10, pady=8)

    def _queue(self):
        self.qtree = ttk.Treeview(self.queue_tab, columns=("event_id", "amount", "risk_score", "decision"), show="headings", height=14)
        for c in ("event_id", "amount", "risk_score", "decision"): self.qtree.heading(c, text=c)
        self.qtree.pack(fill="both", expand=True, padx=10, pady=10)
        bar = ttk.Frame(self.queue_tab); bar.pack(pady=6)
        for label, gt, act in [("Mark FRAUD (block)", "FRAUD", "BLOCK"), ("Mark LEGITIMATE (allow)", "LEGITIMATE", "ALLOW"), ("Unknown (escalate)", "UNKNOWN", "ESCALATE")]:
            ttk.Button(bar, text=label, command=lambda g=gt, a=act: self.feedback(g, a)).pack(side="left", padx=6)

    def feedback(self, gt, act):
        sel = self.qtree.selection()
        if not sel: return
        eid = self.qtree.item(sel[0])["values"][0]
        reason = simpledialog.askstring("Reason", "Reason (required):")
        if not reason: return
        if messagebox.askyesno("Confirm", f"{gt} / {act} for {eid}?"):
            try: api("/api/feedback", {"event_id": eid, "ground_truth": gt, "analyst_action": act, "reason": reason})
            except Exception as e: messagebox.showerror("Error", str(e))

    def show_detail(self, _):
        sel = self.tree.selection()
        if not sel: return
        try: d = api(f"/api/transactions/{self.tree.item(sel[0])['values'][0]}")
        except Exception: return
        x = d["decision"]
        self.detail.delete("1.0", "end")
        self.detail.insert("end", f"{x['event_id']}  risk {x['risk_score']} {x['risk_category']} -> {x['decision']}\n"
                                  f"IsolationForest {x['anomaly_score']}  XGBoost {x['scam_probability']}  policy v{x['policy_version']}\n"
                                  + "\n".join(f"  +{r['pts']}  {r['name']}" for r in x["risk_drivers"]))

    def refresh(self):
        def run():
            try: s, t, q = api("/api/stats"), api("/api/transactions?limit=40"), api("/api/queue")
            except Exception: return self.after(2000, self.refresh)
            self.after(0, lambda: self._paint(s, t, q)); self.after(2000, self.refresh)
        threading.Thread(target=run, daemon=True).start()

    def _paint(self, s, t, q):
        self.kpi.config(text=f"Total {s['total']}   Low {s['low']}   Medium {s['medium']}   High {s['high']}   Avg risk {s['avg_risk'] or 0:.1f}   Avg latency {s['avg_latency_ms'] or 0:.1f} ms")
        self.tree.delete(*self.tree.get_children())
        for r in t:
            self.tree.insert("", "end", values=(r["event_id"], r["amount"], r["merchant_id"], r["city"], r["risk_score"], r["risk_category"], r["decision"], r["latency_ms"]), tags=(r["risk_category"],))
        self.qtree.delete(*self.qtree.get_children())
        for r in q: self.qtree.insert("", "end", values=(r["event_id"], r["amount"], r["risk_score"], r["decision"]))


if __name__ == "__main__":
    App().mainloop()
