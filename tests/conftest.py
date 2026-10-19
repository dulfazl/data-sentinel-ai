"""Shared fixtures: in-memory SQLite, heuristic-only engine, free local ports. No network."""
import os
import socket
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["SENTINEL_COMPANY_DOMAINS"] = "company.com"

from data_sentinel.db import Database  # noqa: E402
from data_sentinel.engine import Engine  # noqa: E402

TEST_CARDS = ["4111111111111111", "5555555555554444", "378282246310005", "6011111111111117",
              "3530111333300000", "30569309025904"]          # published test numbers, not real cards
PAYROLL = "RESTRICTED\nname,card,salary\nTest User,4111 1111 1111 1111,90000\n"


@pytest.fixture
def db():
    d = Database(url="", sqlite_path=":memory:")
    d.init_schema(seed=True)
    yield d
    d.close()


@pytest.fixture
def engine(db):
    """Heuristic-only engine so scores are exact and independent of the saved model."""
    return Engine(db, use_saved_model=False)


@pytest.fixture
def dry_engine(db):
    return Engine(db, dry_run=True, use_saved_model=False)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
