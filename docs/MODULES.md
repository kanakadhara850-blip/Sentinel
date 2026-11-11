# Implemented Modules

Decision path: **TCP/REST ingest → validation → bus → worker pool → features → rules → Isolation Forest ‖ XGBoost → SymPy risk score → policy band → decision → atomic persistence + audit chain → WebSocket → dashboard.**

## Backend (`backend/app/`)

| Module | File(s) | Responsibility |
|--------|---------|----------------|
| Entry point | `main.py`, `context.py` | Wires every component into one process; starts workers, TCP server and API |
| Configuration | `config/settings.py`, `config/policy.json` | Environment settings; versioned policy: thresholds (MEDIUM ≥ 30, HIGH > 75), actions, weights, velocity limits, lists and all business rules |
| Validation | `common/validation.py`, `common/util.py` | Boundary validation, field limits, de-duplication, PII pseudonymisation, time/canonical helpers |
| Transport | `transport/tcp_server.py`, `transport/tcp_client.py` | Socket ingest with message-size limit and optional shared token; client helper |
| Streaming | `streaming/bus.py` | Event bus – in-memory by default, Kafka optional |
| Pipeline | `pipeline/worker.py`, `pipeline/processor.py` | Worker pool and synchronous decision path; hard rules skip ML |
| Feature store | `features/feature_store.py` | Per-customer behaviour, velocity (5 / 15 min), amount ratio, location/device deviation; memory or Redis |
| Rule engine | `rules/rule_engine.py` | Config-driven rules (blacklists, sanctioned region, suspicious IP, excess velocity, amount limit, impossible travel) |
| ML models | `models/train.py`, `models/inference.py` | Time-aware training (70/15/15 chronological split), weight calibration, versioned artifacts; inference for Isolation Forest and XGBoost |
| Risk engine | `risk/risk_engine.py` | SymPy formula compiled once; weighted score 0–100; LOW / MEDIUM / HIGH → ALLOW / CHALLENGE / BLOCK |
| Audit | `audit/immutable_writer.py` | Append-only SHA-256 hash-chained audit records and chain verification |
| Database | `db/database.py`, `db/schema_sqlite.sql`, `db/schema_postgres.sql` | Persistence, version registration, append-only triggers |
| API | `api/server.py` | FastAPI REST + WebSocket (see below) |
| Simulation | `simulation/generator.py` | Synthetic legitimate and fraudulent traffic |
| Desktop UI | `ui/transaction_form.py` | Tkinter transaction submission form |

### REST / WebSocket API
`GET /api/health` · `GET /api/stats` · `GET /api/transactions` · `GET /api/transactions/{event_id}` · `POST /api/transactions` · `GET /api/queue` · `POST /api/feedback` · `GET /api/audit` · `GET /api/audit/verify` · `WS /ws/events`
Optional `X-API-Key` header (REST) / `?key=` (WebSocket) when `API_KEY` is set.

### Scripts (`backend/scripts/`)
`simulate.py` (batch / live traffic) · `load_test.py` · `retrain.py` · `seed_demo_db.py` · `run_all.sh`

### Tests (`backend/tests/`)
`test_validation_rules.py` · `test_risk_engine.py` · `test_audit.py` · `test_pipeline_e2e.py` · `test_tcp_api.py` (run with `cd backend && pytest -q`)

### Model artifacts (`backend/artifacts/`)
`current.json` points to `models/v1791109391/` (`iforest.joblib`, `xgb.json`, `meta.json`).

## Frontend (`frontend/`)
| File | Responsibility |
|------|----------------|
| `public/index.html` | Landing page with simulated demo stats and pipeline story |
| `public/app.html` | Dashboard app: demo auth with roles (Admin, Security Analyst, Fraud Analyst, Auditor, Viewer), Overview risk gauge and KPIs, High-Risk Queue, investigation drawer, Audit Trail with chain verification, System Health; demo (mock) or live (WebSocket) mode |
| `vercel.json` | Routes `/login`, `/dashboard`, `/queue`, `/audit`, `/system` to `app.html` |

Root helpers: `run.py` (starts backend + frontend), `frontend_server.py` (local static server), `.vscode/` launch and task configs.
Frontend auth is demo-only; replace the `Auth` adapter with a real provider before production.
