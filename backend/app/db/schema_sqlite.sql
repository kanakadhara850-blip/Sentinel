-- Real-time risk scoring pipeline: SQLite schema (prototype datastore).
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS model_versions (
  model_name TEXT NOT NULL, model_version TEXT NOT NULL, metrics_json TEXT, feature_schema TEXT, created_at TEXT NOT NULL,
  PRIMARY KEY (model_name, model_version));

CREATE TABLE IF NOT EXISTS policy_versions (
  policy_version TEXT PRIMARY KEY, policy_json TEXT NOT NULL, created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS transaction_events (
  event_id TEXT PRIMARY KEY, transaction_id TEXT NOT NULL, user_hash TEXT NOT NULL, device_hash TEXT, ip_hash TEXT,
  amount REAL NOT NULL, currency TEXT NOT NULL, merchant_id TEXT, merchant_category TEXT, country TEXT, city TEXT,
  channel TEXT, event_time TEXT NOT NULL, received_at TEXT NOT NULL, metadata_json TEXT, processing_status TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_txn_time ON transaction_events(event_time);

CREATE TABLE IF NOT EXISTS feature_snapshots (
  event_id TEXT PRIMARY KEY REFERENCES transaction_events(event_id), features_json TEXT NOT NULL, created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS model_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL REFERENCES transaction_events(event_id),
  model_name TEXT NOT NULL, model_version TEXT NOT NULL, raw_output REAL, normalized_score REAL, inference_ms REAL,
  top_features_json TEXT, created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS risk_decisions (
  event_id TEXT PRIMARY KEY REFERENCES transaction_events(event_id),
  anomaly_score REAL, scam_probability REAL, rule_score REAL, velocity_score REAL, risk_score REAL NOT NULL,
  risk_category TEXT NOT NULL CHECK (risk_category IN ('LOW','MEDIUM','HIGH')),
  decision TEXT NOT NULL CHECK (decision IN ('ALLOW','CHALLENGE','BLOCK','REVIEW')),
  risk_drivers_json TEXT, rules_triggered_json TEXT, policy_version TEXT NOT NULL, latency_ms REAL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_dec_time ON risk_decisions(created_at);

CREATE TABLE IF NOT EXISTS feedback_labels (
  id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL REFERENCES transaction_events(event_id),
  ground_truth TEXT NOT NULL CHECK (ground_truth IN ('FRAUD','LEGITIMATE','UNKNOWN')),
  review_status TEXT NOT NULL DEFAULT 'CONFIRMED' CHECK (review_status IN ('PENDING','CONFIRMED','DISMISSED')),
  analyst_action TEXT NOT NULL, feedback_reason TEXT NOT NULL, label_source TEXT NOT NULL, analyst TEXT, label_time TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS dlq_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL, stage TEXT NOT NULL, error TEXT NOT NULL,
  payload_hash TEXT, created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS audit_log (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, audit_id TEXT NOT NULL UNIQUE, record_type TEXT NOT NULL,
  event_id TEXT NOT NULL, transaction_id TEXT, created_at TEXT NOT NULL, model_versions TEXT, policy_version TEXT,
  risk_score REAL, risk_category TEXT, decision TEXT, risk_drivers TEXT, payload_hash TEXT NOT NULL,
  prev_hash TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE, signature TEXT, actor TEXT NOT NULL, metadata TEXT);
CREATE INDEX IF NOT EXISTS ix_audit_event ON audit_log(event_id);

-- Append-only enforcement: history can never be edited or deleted through SQL. Corrections are new rows.
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log BEGIN SELECT RAISE(ABORT,'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log BEGIN SELECT RAISE(ABORT,'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS dec_no_update BEFORE UPDATE ON risk_decisions BEGIN SELECT RAISE(ABORT,'risk_decisions is append-only'); END;
CREATE TRIGGER IF NOT EXISTS dec_no_delete BEFORE DELETE ON risk_decisions BEGIN SELECT RAISE(ABORT,'risk_decisions is append-only'); END;
CREATE TRIGGER IF NOT EXISTS fb_no_update BEFORE UPDATE ON feedback_labels BEGIN SELECT RAISE(ABORT,'feedback_labels is append-only'); END;
CREATE TRIGGER IF NOT EXISTS fb_no_delete BEFORE DELETE ON feedback_labels BEGIN SELECT RAISE(ABORT,'feedback_labels is append-only'); END;

CREATE VIEW IF NOT EXISTS v_decisions AS
  SELECT t.event_id, t.transaction_id, t.amount, t.currency, t.merchant_id, t.city, t.country, t.channel, t.event_time,
         d.risk_score, d.risk_category, d.decision, d.anomaly_score, d.scam_probability, d.latency_ms,
         d.risk_drivers_json, d.policy_version, d.created_at
  FROM transaction_events t JOIN risk_decisions d USING (event_id);
