"""Message bus abstraction. MemoryBus (dev/tests, same semantics: consumer groups, manual commit) or KafkaBus (deployment).
Consumers in the same group compete for messages (scale out workers); different groups each see every message."""
import json
import queue
from collections import defaultdict
from threading import Lock


class MemoryConsumer:
    def __init__(self, q): self.q, self._pending = q, None
    def poll(self, timeout=0.5):
        try:
            self._pending = self.q.get(timeout=timeout)
            return self._pending
        except queue.Empty:
            return None
    def commit(self): self._pending = None
    def depth(self): return self.q.qsize()


class MemoryBus:
    backend = "memory"

    def __init__(self):
        self.groups, self.lock, self.counts = defaultdict(dict), Lock(), defaultdict(int)

    def subscribe(self, topic, group):
        with self.lock:
            return MemoryConsumer(self.groups[topic].setdefault(group, queue.Queue()))

    def publish(self, topic, msg, key=None):
        self.counts[topic] += 1
        for q in list(self.groups[topic].values()):
            q.put(json.loads(json.dumps(msg, default=str)))      # serialise round-trip, like a real broker

    def healthy(self): return True
    def close(self): pass


class KafkaConsumerWrap:
    def __init__(self, consumer): self.c = consumer
    def poll(self, timeout=0.5):
        batch = self.c.poll(timeout_ms=int(timeout * 1000), max_records=1)
        for recs in batch.values():
            for r in recs:
                return r.value
        return None
    def commit(self): self.c.commit()                           # at-least-once: commit only after processing
    def depth(self): return 0


class KafkaBus:
    backend = "kafka"

    def __init__(self, bootstrap, partitions=3):
        from kafka import KafkaProducer
        self.bootstrap = bootstrap
        self.producer = KafkaProducer(bootstrap_servers=bootstrap, acks="all", retries=5, linger_ms=2,
                                      value_serializer=lambda v: json.dumps(v, default=str).encode(),
                                      key_serializer=lambda k: k.encode() if k else None)

    def ensure_topics(self, topics, partitions=3):
        from kafka.admin import KafkaAdminClient, NewTopic
        from kafka.errors import TopicAlreadyExistsError
        adm = KafkaAdminClient(bootstrap_servers=self.bootstrap)
        for t in topics:
            try:
                adm.create_topics([NewTopic(t, partitions, 1)])
            except TopicAlreadyExistsError:
                pass

    def subscribe(self, topic, group):
        from kafka import KafkaConsumer
        return KafkaConsumerWrap(KafkaConsumer(topic, bootstrap_servers=self.bootstrap, group_id=group, enable_auto_commit=False,
                                               auto_offset_reset="earliest", value_deserializer=lambda v: json.loads(v.decode())))

    def publish(self, topic, msg, key=None):
        self.producer.send(topic, msg, key=key).get(timeout=10)   # key = user hash -> per-user ordering within a partition

    def healthy(self):
        try:
            return bool(self.producer.bootstrap_connected())
        except Exception:
            return False

    def close(self): self.producer.close()


def make_bus(backend, bootstrap, topics):
    if backend == "kafka":
        bus = KafkaBus(bootstrap)
        bus.ensure_topics(list(topics.values()))
        return bus
    return MemoryBus()
