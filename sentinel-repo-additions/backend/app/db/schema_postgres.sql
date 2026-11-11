-- Production DDL for PostgreSQL (same logical model as SQLite). Not exercised by the prototype's tests.
CREATE TABLE model_versions (model_name text, model_version text, metrics_json jsonb, feature_schema jsonb, created_at timestamptz DEFAULT now(), PRIMARY KEY (model_name, model_version));
CREATE TABLE policy_versions (policy_version text PRIMARY KEY, policy_json jsonb NOT NULL, created_at timestamptz DEFAULT now());
CREATE TABLE transaction_events (event_id uuid PRIMARY KEY, transaction_id text NOT NULL, user_hash text NOT NULL, device_hash text, ip_hash text,
  amount numeric(18,2) NOT NULL, currency char(3) NOT NULL, merchant_id text, merchant_category text, country text, city text, channel text,
  event_time timestamptz NOT NULL, received_at timestamptz NOT NULL, metadata_json jsonb, processing_status text NOT NULL);
CREATE INDEX ix_txn_time ON transaction_events(event_time);
CREATE TABLE feature_snapshots (event_id uuid PRIMARY KEY REFERENCES transaction_events, features_json jsonb NOT NULL, created_at timestamptz DEFAULT now());
CREATE TABLE model_results (id bigserial PRIMARY KEY, event_id uuid NOT NULL REFERENCES transaction_events, model_name text NOT NULL, model_version text NOT NULL,
  raw_output double precision, normalized_score double precision, inference_ms double precision, top_features_json jsonb, created_at timestamptz DEFAULT now());
CREATE TABLE risk_decisions (event_id uuid PRIMARY KEY REFERENCES transaction_events, anomaly_score double precision, scam_probability double precision,
  rule_score double precision, velocity_score double precision, risk_score double precision NOT NULL,
  risk_category text NOT NULL CHECK (risk_category IN ('LOW','MEDIUM','HIGH')), decision text NOT NULL CHECK (decision IN ('ALLOW','CHALLENGE','BLOCK','REVIEW')),
  risk_drivers_json jsonb, rules_triggered_json jsonb, policy_version text NOT NULL, latency_ms double precision, created_at timestamptz DEFAULT now());
CREATE TABLE feedback_labels (id bigserial PRIMARY KEY, event_id uuid NOT NULL REFERENCES transaction_events,
  ground_truth text NOT NULL CHECK (ground_truth IN ('FRAUD','LEGITIMATE','UNKNOWN')), review_status text NOT NULL DEFAULT 'CONFIRMED',
  analyst_action text NOT NULL, feedback_reason text NOT NULL, label_source text NOT NULL, analyst text, label_time timestamptz DEFAULT now());
CREATE TABLE dlq_events (id bigserial PRIMARY KEY, event_id text NOT NULL, stage text NOT NULL, error text NOT NULL, payload_hash text, created_at timestamptz DEFAULT now());
CREATE TABLE audit_log (seq bigserial PRIMARY KEY, audit_id uuid NOT NULL UNIQUE, record_type text NOT NULL, event_id text NOT NULL, transaction_id text,
  created_at timestamptz NOT NULL, model_versions jsonb, policy_version text, risk_score double precision, risk_category text, decision text, risk_drivers jsonb,
  payload_hash text NOT NULL, prev_hash text NOT NULL, event_hash text NOT NULL UNIQUE, signature text, actor text NOT NULL, metadata jsonb);

-- Append-only: dedicated writer role may only INSERT; triggers block everyone else, including table owners.
CREATE FUNCTION forbid_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION '% is append-only', TG_TABLE_NAME; END $$ LANGUAGE plpgsql;
CREATE TRIGGER audit_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON audit_log FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER decisions_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON risk_decisions FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER feedback_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON feedback_labels FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation();
-- CREATE ROLE audit_writer; GRANT INSERT, SELECT ON audit_log TO audit_writer; REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM PUBLIC;
