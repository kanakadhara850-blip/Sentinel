import socket

from app.config import settings
from app.transport.tcp_server import recv_frame, send_frame
import json


class TCPClient:
    """Persistent connection client (Tkinter form, simulators)."""
    def __init__(self, host=None, port=None, token=None, timeout=10):
        self.addr, self.token = (host or settings.TCP_HOST, port or settings.TCP_PORT), token if token is not None else settings.TCP_TOKEN
        self.sock = socket.create_connection(self.addr, timeout=timeout)

    def send(self, txn: dict) -> dict:
        msg = {**txn, "auth_token": self.token} if self.token else txn
        send_frame(self.sock, msg)
        return json.loads(recv_frame(self.sock, 1 << 20))

    def close(self):
        self.sock.close()


def send_transaction(txn, host=None, port=None, token=None):
    c = TCPClient(host, port, token)
    try:
        return c.send(txn)
    finally:
        c.close()
