# Real-Time AI-Driven Financial Transaction Risk Scoring Pipeline (backend + database)

```
Tkinter / simulator ─TCP─> validation+pseudonymisation ─> bus: transactions.raw / .validated
  ─> worker pool: Feature store (sliding windows) ─> Rule engine (config) ─> IsolationForest ∥ XGBoost
  ─> SymPy risk engine (lambdified once) ─> LOW/MEDIUM/HIGH ─> decision ─> atomic write: event+features+model results+decision+AUDIT (hash chain)
  ─> bus: .risk-scored / .high-risk / .audit ─> WebSocket + REST ─> web dashboard (separate repo/zip) and Tkinter
  analyst feedback ─> feedback_labels (+ OVERRIDE audit record) ─> scripts/retrain.py ─> new model version (gated promotion)
```

## Quick start (no Kafka/Redis needed)
```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
bash scripts/run_all.sh          # trains a model if none exists, then starts TCP :9009 + API :8000
```
A trained model (`artifacts/`) and a seeded demo database (`data/risk.db`, 600 simulated transactions + analyst labels) are already included, so the backend starts immediately. Delete `data/risk.db` to start with an empty database.

## Step-by-step usage
1. **Start the backend**: `python -m app.main` → logs model version, policy version, bus and feature-store backend.
2. **Send traffic** (second terminal): `python scripts/simulate.py live --rate 5 --fraud-rate 0.15` — or one named scenario: `python scripts/simulate.py scenario scam` (`normal, high_frequency, unusual_amount, new_device, unusual_location, suspicious_merchant, repeated, scam`).
3. **Or use the Tkinter app**: `python -m app.ui.transaction_form` → *Transaction Entry* tab → Submit. *Live Dashboard* shows the stream (select a row for drivers/model outputs), *High-Risk Queue* lets an analyst mark FRAUD / LEGITIMATE / UNKNOWN (confirmation + required reason).
4. **Connect the web dashboard**: open the Vercel/static site with `?ws=ws://localhost:8000/ws/events` (browsers allow `ws://localhost` from HTTPS pages; for a remote backend use `wss://` behind a TLS proxy).
5. **Inspect results**: `curl localhost:8000/api/stats`, `/api/transactions?limit=20`, `/api/queue`, `/api/transactions/<event_id>`, `/api/health`, `/api/audit`, `/api/audit/verify`. Interactive docs: http://localhost:8000/docs
6. **Replay a CSV**: `python scripts/simulate.py gen-csv --n 5000` then `python scripts/simulate.py replay --csv data/simulated/transactions.csv --rate 50`
7. **Give feedback** (API): `POST /api/feedback {"event_id","ground_truth","analyst_action","reason"}`.
8. **Retrain**: `python scripts/retrain.py` → uses analyst labels, promotes the new version only if test PR-AUC does not regress; restart the backend to load it.
9. **Verify tamper-evidence**: `curl localhost:8000/api/audit/verify`.

## With Kafka + Redis
`docker compose up -d` then `BUS_BACKEND=kafka REDIS_URL=redis://localhost:6379/0 python -m app.main`. Topics (`transactions.raw|validated|risk-scored|high-risk|audit|feedback|dlq`) are created automatically; workers form consumer group `risk-workers` (scale with `WORKERS=N` or more processes), offsets are committed only after processing (at-least-once; processing is idempotent on `event_id`). Producers publish with `acks=all` and retries, keyed by pseudonymous user id.

## Database (`data/risk.db`, SQLite) — see `app/db/schema_sqlite.sql`
`transaction_events`, `feature_snapshots`, `model_results`, `risk_decisions`, `feedback_labels`, `dlq_events`, `audit_log`, `model_versions`, `policy_versions`, view `v_decisions`. `schema_postgres.sql` is the equivalent production DDL (JSONB, roles, statement-level immutability triggers).
**Immutability:** triggers reject UPDATE/DELETE on `audit_log`, `risk_decisions`, `feedback_labels`. Each audit row stores `prev_hash` and `event_hash = SHA-256(record)`, plus an HMAC `signature` (key from `AUDIT_SIGNING_KEY`). A privileged actor who drops the trigger and edits a row is still caught by `verify_chain()` (tested). Corrections/overrides are new `OVERRIDE` records.

## Key design points
- **Validation at the socket boundary** (types, ranges, ISO time, size cap 64 KB, duplicate/replay `transaction_id`, optional `TCP_TOKEN`); rejects → `dlq_events` + `REJECTED` audit record + DLQ topic. Required fields are config (`policy.json`).
- **PII minimisation:** user, device and IP are HMAC-pseudonymised before entering the bus/DB; raw IPs are never stored; blacklist entries are hashed the same way.
- **Features** (`app/features`): txn counts 5/15 min, 15-min amount sum, amount vs own history, device change, new merchant, location deviation, new-user flag, hour. Computed from state *before* the current event is added; identical code in training and inference.
- **Rules** are data (`policy.json`): blacklists, suspicious IP prefix, excess velocity, amount limit, impossible travel, sanctioned region. Hard rules skip ML and force HIGH + BLOCK/REVIEW.
- **Risk formula** (SymPy, lambdified once): `100·(w_ml·(s·anomaly+(1−s)·scam)+w_amt·amount_n+w_vel·velocity_n+w_rule·rule_n)/Σw`. Weights are **calibrated on the validation block** (max PR-AUC) and stored with the model version; tests assert bounds, thresholds and that the function is never rebuilt.
- **Policy v1.0.0:** LOW 0–29.99 → ALLOW, MEDIUM 30–75 → CHALLENGE, HIGH >75 → BLOCK; editable and versioned in `policy.json` (stored in `policy_versions`).
- **Explainability:** exact TreeSHAP from XGBoost (`pred_contribs`) for MEDIUM/HIGH, merged with triggered rules → top-3 drivers with indicative points.
- **Failure handling:** worker retries with exponential backoff → DLQ; redelivery idempotent; dashboard/API failure cannot affect scoring (separate consumer group); feature-store falls back to in-memory if Redis is unreachable.

## Tests & benchmarks
`pytest -q` → 27 tests (risk engine, validation, rules, audit immutability/tamper detection, end-to-end, DLQ/retry, idempotency, TCP framing, REST + WebSocket).
`python scripts/load_test.py --n 3000 --workers 4` reports throughput and p50/p95/p99 of the synchronous path. Measured in the build sandbox (SQLite, in-memory bus, 1 worker): p50 ≈ 10 ms, p95 ≈ 15 ms — re-measure on your hardware; it says nothing about Kafka/Redis network latency.

## Honest limitations
- **No dataset was supplied**, so training uses Faker-simulated data (`app/simulation/generator.py`, ~10% positive rate). Reported metrics (XGBoost PR-AUC ≈ 0.87, ROC-AUC ≈ 0.95 on the held-out test block) are for that synthetic data only and say nothing about real-world fraud performance. When you have a real dataset, profile it, map columns to the canonical schema, and retrain.
- Kafka and Redis backends are implemented but were **not run** in this build (tests use the in-memory equivalents); Postgres DDL is provided but the runtime uses SQLite.
- Deep analysis/explainability runs inline for MEDIUM/HIGH events rather than on a separate asynchronous consumer; Isolation Forest + XGBoost run sequentially by default (`PARALLEL_ML=1` uses a thread pool — usually slower at ~1 ms inference).
- Prototype security: shared-token/API-key auth only; use TLS, mTLS/service identity, a secrets manager and DB roles in any real deployment. Not a production banking authorisation system.

## Layout
`app/{ui,transport,streaming,features,models,rules,risk,audit,db,pipeline,api,simulation,config,common}` · `scripts/` · `tests/` · `artifacts/` (versioned models) · `data/{raw,simulated,processed}`
