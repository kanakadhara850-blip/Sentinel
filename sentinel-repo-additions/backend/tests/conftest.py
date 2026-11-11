import pytest

from app.config import settings
from app.context import build_context
from app.models.train import train
from app.simulation.generator import TxnGenerator


@pytest.fixture(scope="session")
def artifacts(tmp_path_factory):
    d = tmp_path_factory.mktemp("artifacts")
    train(n=5000, artifact_dir=d, quiet=True)
    return d


@pytest.fixture()
def ctx(tmp_path, artifacts):
    return build_context(db_path=str(tmp_path / "t.db"), artifact_dir=artifacts, bus_backend="memory", workers=1)


def drain(ctx, limit=100):
    """Process everything currently queued on the validated topic (synchronous, deterministic for tests)."""
    c, out = ctx.workers.consumers[0], []
    for _ in range(limit):
        m = c.poll(0.05)
        if m is None:
            break
        out.append(ctx.workers.handle(m))
        c.commit()
    return out


def sample_txn(**kw):
    t = TxnGenerator(seed=1).scenario("normal")[0][0]
    t.update(kw)
    return t
