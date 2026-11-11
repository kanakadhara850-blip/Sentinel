"""Run the whole backend in one process:  python -m app.main
TCP :9009 -> validation -> bus -> worker pool -> SQLite audit store -> REST/WebSocket :8000"""
import logging

import uvicorn

from app.api.server import create_app
from app.config import settings
from app.context import build_context
from app.transport.tcp_server import TCPIngestServer


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ctx = build_context()
    app = create_app(ctx)                                           # subscribes the dashboard consumer first
    ctx.workers.start()
    TCPIngestServer((settings.TCP_HOST, settings.TCP_PORT), ctx.ingest, settings.MAX_MESSAGE_BYTES).start()
    logging.info("model=%s policy=%s bus=%s feature_store=%s tcp=%s:%s api=%s:%s", ctx.bundle.version, ctx.policy["policy_version"],
                 ctx.bus.backend, ctx.fs.backend, settings.TCP_HOST, settings.TCP_PORT, settings.API_HOST, settings.API_PORT)
    uvicorn.run(app, host=settings.API_HOST, port=settings.API_PORT, log_level="warning")


if __name__ == "__main__":
    main()
