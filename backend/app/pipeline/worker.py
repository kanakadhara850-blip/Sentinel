"""Competing-consumer workers: poll -> process with retry/backoff -> publish -> commit offset (at-least-once).
Exhausted retries go to transactions.dlq; processing is idempotent on event_id so a redelivery never double-writes."""
import logging
import sqlite3
import threading
import time

from app.common.util import sha256, canonical

log = logging.getLogger("worker")


class WorkerPool:
    def __init__(self, bus, processor, db, audit, topics, workers=2, max_retries=3, group="risk-workers"):
        self.bus, self.proc, self.db, self.audit, self.topics, self.max_retries, self.group = bus, processor, db, audit, topics, max_retries, group
        self.consumers = [bus.subscribe(topics["validated"], group) for _ in range(workers)]
        self.stop, self.threads = threading.Event(), []

    def start(self):
        self.threads = [threading.Thread(target=self._loop, args=(c,), daemon=True, name=f"worker-{i}") for i, c in enumerate(self.consumers)]
        [t.start() for t in self.threads]
        return self

    def alive(self): return sum(t.is_alive() for t in self.threads)

    def lag(self): return sum(c.depth() for c in self.consumers[:1])

    def _loop(self, consumer):
        while not self.stop.is_set():
            msg = consumer.poll(0.5)
            if msg is not None:
                self.handle(msg)
                consumer.commit()

    def handle(self, ev):
        if self.db.event_exists(ev["event_id"]):                 # redelivery after crash: already done
            return
        err = None
        for attempt in range(1, self.max_retries + 1):
            try:
                res = self.proc.process(ev)
                self.bus.publish(self.topics["scored"], res)
                if res["risk_category"] == "HIGH":
                    self.bus.publish(self.topics["high"], res)
                self.bus.publish(self.topics["audit"], {"event_id": ev["event_id"], "decision": res["decision"], "risk_score": res["risk_score"]})
                return res
            except sqlite3.IntegrityError:
                return None                                       # concurrent duplicate; first write wins
            except Exception as e:                                # retry with exponential backoff
                err = e
                log.warning("process failed (attempt %s/%s) %s: %s", attempt, self.max_retries, ev.get("event_id"), e)
                time.sleep(0.05 * 2 ** attempt)
        self.db.save_dlq(ev["event_id"], "PROCESSING", repr(err), sha256(canonical(ev)))
        self.bus.publish(self.topics["dlq"], {"event_id": ev["event_id"], "stage": "PROCESSING", "errors": [repr(err)]})

    def shutdown(self):
        self.stop.set()
