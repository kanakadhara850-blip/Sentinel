"""TCP socket boundary: length-prefixed JSON frames (4-byte big-endian length), size-capped, optional shared token.
Every frame is validated; valid events go to transactions.validated, rejects go to the DLQ + an audit REJECTED record."""
import json
import socketserver
import struct
import threading
import uuid

from app.common.util import canonical, sha256, utcnow_iso
from app.common.validation import ValidationError


def recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return buf


def send_frame(sock, obj):
    data = json.dumps(obj).encode()
    sock.sendall(struct.pack(">I", len(data)) + data)


def recv_frame(sock, max_bytes):
    (n,) = struct.unpack(">I", recv_exact(sock, 4))
    if n > max_bytes:
        raise ValueError("frame too large")
    return recv_exact(sock, n)


class IngestService:
    """Transport-independent ingestion (used by the TCP server and the HTTP API)."""
    def __init__(self, validator, bus, db, audit, topics, token=""):
        self.validator, self.bus, self.db, self.audit, self.topics, self.token = validator, bus, db, audit, topics, token

    def handle_bytes(self, data: bytes) -> dict:
        try:
            raw = json.loads(data.decode("utf-8"))
        except Exception:
            return self._reject("MALFORMED_JSON", ["payload is not valid UTF-8 JSON"], sha256(data.hex()))
        if self.token:
            if not isinstance(raw, dict) or raw.pop("auth_token", None) != self.token:
                return self._reject("AUTH", ["invalid or missing auth_token"], sha256(data.hex()))
        elif isinstance(raw, dict):
            raw.pop("auth_token", None)
        return self.handle_dict(raw)

    def handle_dict(self, raw) -> dict:
        try:
            ev = self.validator.validate(raw)
        except ValidationError as e:
            return self._reject("VALIDATION", e.errors, sha256(canonical(raw)))
        self.bus.publish(self.topics["raw"], {"event_id": ev["event_id"], "received_at": ev["received_at"], "payload_sha256": sha256(canonical(raw))})
        self.bus.publish(self.topics["validated"], ev, key=ev["user_id"])
        return {"status": "ACCEPTED", "event_id": ev["event_id"], "transaction_id": ev["transaction_id"]}

    def _reject(self, stage, errors, payload_hash):
        eid = str(uuid.uuid4())
        msg = "; ".join(errors)
        self.db.save_dlq(eid, stage, msg, payload_hash)
        self.audit.append("REJECTED", eid, payload={"stage": stage, "errors": errors, "payload_hash": payload_hash}, decision="REJECTED")
        self.bus.publish(self.topics["dlq"], {"event_id": eid, "stage": stage, "errors": errors, "at": utcnow_iso()})
        return {"status": "REJECTED", "event_id": eid, "errors": errors}


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(15)
        while True:
            try:
                data = recv_frame(self.request, self.server.max_bytes)
            except (ConnectionError, TimeoutError, OSError):
                return
            except ValueError as e:
                send_frame(self.request, {"status": "REJECTED", "errors": [str(e)]})
                return
            send_frame(self.request, self.server.ingest.handle_bytes(data))


class TCPIngestServer(socketserver.ThreadingTCPServer):
    allow_reuse_address, daemon_threads = True, True

    def __init__(self, addr, ingest, max_bytes):
        super().__init__(addr, _Handler)
        self.ingest, self.max_bytes = ingest, max_bytes

    def start(self):
        threading.Thread(target=self.serve_forever, daemon=True, name="tcp-server").start()
        return self
