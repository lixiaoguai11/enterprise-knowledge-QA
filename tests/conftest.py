import os
import sys
import tempfile
from pathlib import Path

os.environ["DATABASE_URL"] = f"sqlite:///{Path(tempfile.gettempdir()) / 'kbqa-agent-tests.sqlite'}"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import pytest

from app import retrieval
from app.database import Base, engine, init_db


@pytest.fixture(autouse=True)
def reset_database():
    Base.metadata.drop_all(bind=engine)
    init_db()
    retrieval.index = retrieval.BM25Index()
    yield
    Base.metadata.drop_all(bind=engine)
