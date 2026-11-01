"""GET /v1/progress and /v1/progress/{document}: the semantics from docs/api.md."""

import pytest

from conftest import AUTH, DOCUMENT, session

OTHER_DOCUMENT = "f" * 32


def post(client, **overrides):
    body = session(**overrides)
    assert client.post("/v1/events/reader-session", json=body, headers=AUTH).status_code == 204


def latest(client, document=DOCUMENT):
    return client.get(f"/v1/progress/{document}", headers=AUTH)


def test_one_document_returns_the_same_object_as_the_list(client):
    post(client)

    only = client.get("/v1/progress", headers=AUTH).json()["documents"][0]
    assert latest(client).json() == only
    assert set(only) == {"document", "progress", "end_bp", "end_time", "ts", "received_at"}


def test_rereading_earlier_chapters_moves_the_position_back(client):
    post(client, id="00000001-1", end_bp=9000, end_time=1793520754)
    post(client, id="00000001-2", end_bp=1000, end_time=1793530000)

    assert latest(client).json()["end_bp"] == 1000
    assert latest(client).json()["progress"] == 0.1


def test_a_late_delivery_of_an_older_session_does_not_win(client):
    post(client, id="00000001-2", end_bp=1000, end_time=1793530000)
    post(client, id="00000001-1", end_bp=9000, end_time=1793520754)

    assert latest(client).json()["end_bp"] == 1000


def test_equal_end_time_goes_to_the_greater_ts(client):
    post(client, id="00000001-1", end_bp=2000, ts=200)
    post(client, id="00000001-2", end_bp=1000, ts=100)

    assert latest(client).json()["end_bp"] == 2000


def test_equal_end_time_and_ts_go_to_the_most_recently_received(client):
    post(client, id="ffffffff-1", end_bp=1000, ts=100)
    post(client, id="00000001-2", end_bp=2000, ts=100)

    assert latest(client).json()["end_bp"] == 2000


def test_the_list_has_one_entry_per_document_most_recently_read_first(client):
    post(client, id="00000001-1", document=DOCUMENT, end_time=1793520100)
    post(client, id="00000001-2", document=DOCUMENT, end_time=1793520200)
    post(client, id="00000001-3", document=OTHER_DOCUMENT, end_time=1793520300)

    documents = client.get("/v1/progress", headers=AUTH).json()["documents"]
    assert [row["document"] for row in documents] == [OTHER_DOCUMENT, DOCUMENT]
    assert documents[1]["end_time"] == 1793520200


def test_no_sessions_is_an_empty_list(client):
    assert client.get("/v1/progress", headers=AUTH).json() == {"documents": []}


def test_a_document_without_sessions_is_404(client):
    assert latest(client, OTHER_DOCUMENT).status_code == 404


@pytest.mark.parametrize(
    "document",
    ["abc", DOCUMENT.upper(), DOCUMENT + "%0A", "%00", "%ff", "%ED%A0%80", "x" * 5000, "'--"],
)
def test_a_bad_document_in_the_path_is_404(client, document):
    assert latest(client, document).status_code == 404
