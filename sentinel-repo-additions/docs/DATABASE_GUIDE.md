# Database Guide

Files added:
- `database/risk.db` – seeded SQLite database (also what the backend uses at `backend/data/risk.db`)
- `database/schema_sqlite.sql`, `database/schema_postgres.sql` – DDL
- `database/exports/*.csv` – `decisions`, `audit_log`, `feedback_labels`, `dlq_events`
- `database/DATABASE.md` – original short description

## Seeded contents
| Table | Rows |
|-------|------|
| transaction_events | 601 |
| risk_decisions | 601 (LOW 476 · MEDIUM 82 · HIGH 43) |
| feedback_labels | 40 |
| dlq_events | 1 (rejected malformed event) |
| audit_log | 642 (hash-chained) |
| model_versions | 2 |
| policy_versions | 1 |

Other tables: `feature_snapshots`, `model_results`.

## Integrity
`audit_log`, `risk_decisions` and `feedback_labels` have triggers that reject UPDATE and DELETE (`... is append-only`). Each audit record's SHA-256 covers the previous hash plus the record, so editing history breaks every later link (`GET /api/audit/verify`).

## Quick queries
```bash
sqlite3 database/risk.db "SELECT risk_category, COUNT(*) FROM risk_decisions GROUP BY 1;"
sqlite3 database/risk.db "UPDATE audit_log SET decision='ALLOW'"   # -> Runtime error: audit_log is append-only
```
