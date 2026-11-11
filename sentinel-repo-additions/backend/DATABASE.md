# Database package
- `risk.db` — seeded SQLite database (600 simulated transactions scored by the real pipeline, 1 rejected malformed event, 1 hard-rule block, 40 analyst feedback labels, 642+ hash-chained audit records).
- `schema_sqlite.sql` / `schema_postgres.sql` — DDL (append-only triggers included).
- `exports/*.csv` — decisions, audit log, feedback labels, DLQ.
Open: `sqlite3 risk.db "SELECT risk_category, COUNT(*) FROM risk_decisions GROUP BY 1;"`
Verify immutability: `sqlite3 risk.db "UPDATE audit_log SET decision='ALLOW'"` → `Runtime error: audit_log is append-only`.
