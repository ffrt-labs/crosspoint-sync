import pytest

from conftest import AUTH, CONTRACT_BODY

URL = "/v1/events/reader-session"


@pytest.fixture
def broken_db(db_path, client):
    """The database file is unusable while the test runs, and restored at the end."""
    good = db_path.read_bytes()
    db_path.write_bytes(b"this is not a sqlite database, not at all" * 50)
    yield
    db_path.write_bytes(good)


def test_healthz_needs_no_token(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_is_503_when_the_database_is_unusable(client, broken_db):
    assert client.get("/healthz").status_code == 503


def test_database_faults_are_5xx_so_the_event_retries(client, db_path):
    good = db_path.read_bytes()
    db_path.write_bytes(b"this is not a sqlite database, not at all" * 50)

    assert client.post(URL, content=CONTRACT_BODY, headers=AUTH).status_code == 503

    db_path.write_bytes(good)
    assert client.post(URL, content=CONTRACT_BODY, headers=AUTH).status_code == 204
    assert len(client.get("/v1/progress", headers=AUTH).json()["documents"]) == 1


def test_read_faults_are_5xx(client, broken_db):
    assert client.get("/v1/progress", headers=AUTH).status_code == 503
