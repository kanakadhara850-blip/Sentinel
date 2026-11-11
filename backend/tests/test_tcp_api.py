import socket
import struct
import time

from fastapi.testclient import TestClient

from app.api.server import create_app
from app.transport.tcp_client import TCPClient
from app.transport.tcp_server import TCPIngestServer, recv_frame
from tests.conftest import drain, sample_txn


def test_tcp_roundtrip_and_rejections(ctx):
    srv = TCPIngestServer(("127.0.0.1", 0), ctx.ingest, 64 * 1024).start()
    port = srv.server_address[1]
    c = TCPClient("127.0.0.1", port, token="")
    assert c.send(sample_txn())["status"] == "ACCEPTED"
    assert c.send({"amount": "x"})["status"] == "REJECTED"
    c.sock.sendall(struct.pack(">I", 5) + b"{bad}")                  # malformed JSON frame
    import json
    assert json.loads(recv_frame(c.sock, 4096))["status"] == "REJECTED"
    c.close()
    s = socket.create_connection(("127.0.0.1", port))                # oversized frame announced
    s.sendall(struct.pack(">I", 10_000_000))
    assert "too large" in recv_frame(s, 4096).decode()
    s.close(); srv.shutdown()
    assert len(drain(ctx)) == 1


def test_api_endpoints_and_websocket(ctx):
    app = create_app(ctx)
    with TestClient(app) as cl:
        with cl.websocket_connect("/ws/events") as ws:
            r = cl.post("/api/transactions", json=sample_txn()).json()
            assert r["status"] == "ACCEPTED"
            res = drain(ctx)[0]
            ctx.bus.publish("transactions.risk-scored", res)             # worker.handle already published; drain consumed one copy
            msg = ws.receive_json()
            assert msg["event_id"] == r["event_id"] and "risk_score" in msg
        assert cl.get("/api/stats").json()["total"] == 1
        assert cl.get("/api/health").json()["audit_chain_ok"] is True
        d = cl.get(f"/api/transactions/{r['event_id']}").json()
        assert d["decision"]["event_id"] == r["event_id"] and len(d["model_results"]) == 2
        fb = {"event_id": r["event_id"], "ground_truth": "FRAUD", "analyst_action": "BLOCK", "reason": "chargeback"}
        assert cl.post("/api/feedback", json=fb).json()["status"] == "RECORDED"
        assert cl.post("/api/feedback", json={**fb, "ground_truth": "??"}).status_code == 422
        assert cl.get("/api/audit/verify").json()["chain_ok"] is True
