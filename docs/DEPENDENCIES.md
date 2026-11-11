# Libraries & Dependencies

Python 3.10+ is required. Install everything with:

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r backend/requirements.txt
```

## Python (backend) – from `backend/requirements.txt`

| Library | Min version | Used for |
|---------|-------------|----------|
| numpy | 1.26 | Numeric arrays, vectorised risk scoring |
| pandas | 2.1 | Training dataset construction and time-aware splits |
| scikit-learn | 1.4 | Isolation Forest (anomaly), evaluation metrics |
| xgboost | 2.0 | Scam-probability classifier |
| sympy | 1.12 | Risk formula, lambdified once at start-up (`app/risk/risk_engine.py`) |
| faker | 24.0 | Synthetic transaction generator |
| joblib | 1.3 | Saving / loading the Isolation Forest artifact |
| fastapi | 0.110 | REST API + WebSocket (`/ws/events`) |
| uvicorn[standard] | 0.29 | ASGI server |
| httpx | 0.27 | API tests / client calls |
| pytest | 8.0 | Test suite |
| kafka-python *(optional)* | 2.0 | Kafka bus backend (`BUS_BACKEND=kafka`) |
| redis *(optional)* | 5.0 | Redis feature store (`REDIS_URL`) |

Standard library modules used: `sqlite3`, `socket`, `threading`, `hashlib`, `hmac`, `json`, `logging`, `concurrent.futures`, `argparse`.
The system runs without Kafka/Redis using in-memory fallbacks.

## Frontend
No build step and no npm dependencies – plain HTML/CSS/JS (`frontend/public/index.html`, `frontend/public/app.html`), deployed to Vercel with `frontend/vercel.json`. Locally served by `frontend_server.py`.

## Infrastructure (optional, `backend/docker-compose.yml`)
| Service | Image | Purpose |
|---------|-------|---------|
| Kafka | apache/kafka:3.7.0 | Production event bus |
| Redis | redis:7-alpine | Shared feature store |
| PostgreSQL | postgres:16-alpine | Production DDL (`schema_postgres.sql`); runtime uses SQLite |

## Ports
Frontend `3000` · REST/WebSocket API `8000` (docs at `/docs`) · TCP ingest `9009`.

## Environment variables (`backend/.env.example`)
`BUS_BACKEND`, `KAFKA_BOOTSTRAP`, `REDIS_URL`, `DB_PATH`, `PSEUDONYM_KEY`, `AUDIT_SIGNING_KEY`, `TCP_TOKEN`, `API_KEY`, `WORKERS`. Replace the `change-me-*` values and never commit real secrets.
