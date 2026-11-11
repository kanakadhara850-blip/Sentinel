"""REST + WebSocket bridge for the web dashboard. Runs beside (never inside) the decision path: if the dashboard is down or slow,
scoring continues unaffected."""
import asyncio
import json
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import settings


def ui_event(r: dict) -> dict:
    """Result -> the event shape the web dashboard consumes."""
    return {**r, "risk_drivers": [{"name": d["name"], "pts": d["pts"]} for d in r["risk_drivers"]]}


class FeedbackIn(BaseModel):
    event_id: str
    ground_truth: str
    analyst_action: str
    reason: str
    source: str = "analyst"
    analyst: str = "analyst"


def create_app(ctx) -> FastAPI:
    clients: set = set()
    consumer = ctx.bus.subscribe(settings.TOPICS["scored"], "dashboard")      # subscribe before traffic starts
    state = {"loop": None}

    def pump():
        while True:
            msg = consumer.poll(0.5)
            if msg is not None and state["loop"]:
                for q in list(clients):
                    state["loop"].call_soon_threadsafe(lambda q=q, m=msg: q.full() or q.put_nowait(m))
                consumer.commit()

    @asynccontextmanager
    async def lifespan(app):
        state["loop"] = asyncio.get_running_loop()
        threading.Thread(target=pump, daemon=True, name="ws-pump").start()
        yield

    app = FastAPI(title="Risk Scoring API", version="1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    def auth(x_api_key: str = Header(None)):
        if settings.API_KEY and x_api_key != settings.API_KEY:
            raise HTTPException(401, "invalid API key")

    @app.websocket("/ws/events")
    async def ws_events(ws: WebSocket, key: str = ""):
        if settings.API_KEY and key != settings.API_KEY:
            await ws.close(code=4401)
            return
        await ws.accept()
        q = asyncio.Queue(maxsize=200)
        clients.add(q)
        try:
            while True:
                await ws.send_text(json.dumps(ui_event(await q.get())))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            clients.discard(q)

    @app.get("/api/health", dependencies=[Depends(auth)])
    def health():
        lat = ctx.db.query("SELECT latency_ms FROM risk_decisions ORDER BY created_at DESC LIMIT 200")
        v = sorted(x["latency_ms"] for x in lat)
        ok, n, bad = ctx.audit.verify_chain()
        return {"status": "ok" if ctx.workers.alive() else "degraded", "workers_alive": ctx.workers.alive(), "queue_lag": ctx.workers.lag(),
                "bus": ctx.bus.backend, "bus_healthy": ctx.bus.healthy(), "feature_store": ctx.fs.backend, "feature_store_healthy": ctx.fs.ping(),
                "model_version": ctx.bundle.version, "policy_version": ctx.policy["policy_version"],
                "latency_ms_p50": v[len(v) // 2] if v else None, "latency_ms_p95": v[int(len(v) * .95)] if v else None,
                "audit_chain_ok": ok, "audit_records": n, "dlq_count": ctx.db.query("SELECT COUNT(*) c FROM dlq_events")[0]["c"]}

    @app.get("/api/stats", dependencies=[Depends(auth)])
    def stats():
        c = {r["risk_category"]: r["n"] for r in ctx.db.query("SELECT risk_category, COUNT(*) n FROM risk_decisions GROUP BY 1")}
        a = ctx.db.query("SELECT COUNT(*) n, AVG(risk_score) s, AVG(latency_ms) l, SUM(decision IN ('BLOCK','REVIEW')) b FROM risk_decisions")[0]
        pm = ctx.db.query("SELECT COUNT(*) n FROM risk_decisions WHERE created_at > datetime('now','-1 minute')")[0]["n"]
        n = a["n"] or 0
        return {"total": n, "low": c.get("LOW", 0), "medium": c.get("MEDIUM", 0), "high": c.get("HIGH", 0), "avg_risk": a["s"], "avg_latency_ms": a["l"],
                "block_rate": (a["b"] or 0) / n if n else 0, "per_minute": pm}

    @app.get("/api/transactions", dependencies=[Depends(auth)])
    def transactions(limit: int = Query(50, le=500), category: str = None):
        sql = "SELECT * FROM v_decisions " + ("WHERE risk_category=? " if category else "") + "ORDER BY created_at DESC LIMIT ?"
        rows = ctx.db.query(sql, (category, limit) if category else (limit,))
        for r in rows:
            r["risk_drivers"] = json.loads(r.pop("risk_drivers_json") or "[]")
        return rows

    @app.get("/api/transactions/{event_id}", dependencies=[Depends(auth)])
    def detail(event_id: str):
        d = ctx.db.query("SELECT * FROM v_decisions WHERE event_id=?", (event_id,))
        if not d:
            raise HTTPException(404, "unknown event_id")
        d = d[0]
        d["risk_drivers"] = json.loads(d.pop("risk_drivers_json") or "[]")
        return {"decision": d, "features": json.loads(ctx.db.query("SELECT features_json f FROM feature_snapshots WHERE event_id=?", (event_id,))[0]["f"]),
                "model_results": ctx.db.query("SELECT model_name,model_version,raw_output,normalized_score,inference_ms FROM model_results WHERE event_id=?", (event_id,)),
                "audit": ctx.audit.recent(20, event_id), "feedback": ctx.db.query("SELECT * FROM feedback_labels WHERE event_id=?", (event_id,))}

    @app.post("/api/transactions", dependencies=[Depends(auth)])
    def submit(txn: dict):
        return ctx.ingest.handle_dict(txn)

    @app.get("/api/queue", dependencies=[Depends(auth)])
    def queue(limit: int = 50):
        """HIGH-risk transactions with no analyst label yet."""
        rows = ctx.db.query("""SELECT v.* FROM v_decisions v WHERE v.risk_category='HIGH' AND NOT EXISTS
                               (SELECT 1 FROM feedback_labels f WHERE f.event_id=v.event_id) ORDER BY v.created_at DESC LIMIT ?""", (limit,))
        for r in rows:
            r["risk_drivers"] = json.loads(r.pop("risk_drivers_json") or "[]")
        return rows

    @app.post("/api/feedback", dependencies=[Depends(auth)])
    def feedback(fb: FeedbackIn):
        try:
            rec = ctx.audit.record_feedback(fb.event_id, fb.ground_truth, fb.analyst_action, fb.reason, fb.source, fb.analyst)
        except LookupError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))
        ctx.bus.publish(settings.TOPICS["feedback"], fb.model_dump())
        return {"status": "RECORDED", "audit_id": rec["audit_id"], "event_hash": rec["event_hash"]}

    @app.get("/api/audit", dependencies=[Depends(auth)])
    def audit(limit: int = Query(50, le=500)):
        return ctx.audit.recent(limit)

    @app.get("/api/audit/verify", dependencies=[Depends(auth)])
    def verify():
        ok, n, bad = ctx.audit.verify_chain()
        return {"chain_ok": ok, "records_checked": n, "first_bad_seq": bad}

    return app
