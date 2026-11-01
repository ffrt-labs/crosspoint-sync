"""Tests drive the service over HTTP, the seam the plugin and the readers use."""

import pytest
from fastapi.testclient import TestClient

from progress_endpoint.app import create_app
from progress_endpoint.config import Config

API_KEY = "test-sync-key"
AUTH = {"Authorization": f"Bearer {API_KEY}"}
DOCUMENT = "0123456789abcdef0123456789abcdef"
# The delivered body from docs/api.md, verbatim.
CONTRACT_BODY = (
    b'{"id":"3fa9c21b-7","document":"0123456789abcdef0123456789abcdef",'
    b'"start_bp":4100,"end_bp":4523,"duration_s":754,"start_time":1793520000,'
    b'"end_time":1793520754,"ts":1793521200}'
)


def session(**overrides):
    """A valid event as a dict; overrides replace or add fields."""
    return {
        "id": "3fa9c21b-7",
        "document": DOCUMENT,
        "start_bp": 4100,
        "end_bp": 4523,
        "duration_s": 754,
        "start_time": 1793520000,
        "end_time": 1793520754,
        "ts": 1793521200,
    } | overrides


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "data" / "progress.db"


@pytest.fixture
def app(db_path):
    return create_app(Config(api_key=API_KEY, db_path=db_path))


@pytest.fixture
def client(app):
    return TestClient(app)
