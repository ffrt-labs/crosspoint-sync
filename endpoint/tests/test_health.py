import os

import pytest

from conftest import AUTH, CONTRACT_BODY

URL = "/v1/events/reader-session"
UNPRIVILEGED_UID = 65534


@pytest.fixture
def broken_db(db_path, client):
    """The database file is unusable while the test runs, and restored at the end."""
    good = db_path.read_bytes()
    db_path.write_bytes(b"this is not a sqlite database, not at all" * 50)
    yield
    db_path.write_bytes(good)


@pytest.fixture
def unwritable_db(db_path, client):
    """The database can be read but not written, as after a restore done as root.

    Root ignores file modes, so a root test run drops to another uid, which then
    needs a way through the temporary directories.
    """
    db_path.chmod(0o444)
    if os.geteuid() != 0:
        yield
        return
    for directory in db_path.parents:
        directory.chmod(directory.stat().st_mode | 0o111)
    db_path.parent.chmod(0o777)
    os.seteuid(UNPRIVILEGED_UID)
    yield
    os.seteuid(0)


def test_healthz_needs_no_token(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_is_503_when_the_database_is_unusable(client, broken_db):
    assert client.get("/healthz").status_code == 503


def test_healthz_is_503_when_the_database_is_not_writable(client, unwritable_db):
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
