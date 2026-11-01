"""POST /v1/events/reader-session: the response policy from docs/api.md."""

import json
import logging

import pytest

from asgi import call
from conftest import API_KEY, AUTH, DOCUMENT, session

URL = "/v1/events/reader-session"
MAX_INT = 2**53 - 1
# The plugin's body template sent with nothing substituted.
TEMPLATE = (
    b'{"id":"{event.id}","document":"{event.document}",'
    b'"start_bp":{event.start_progress_bp},"end_bp":{event.end_progress_bp},'
    b'"duration_s":{event.duration_seconds},"start_time":{event.start_time},'
    b'"end_time":{event.end_time},"ts":{event.ts}}'
)
FIELDS = list(session())
INTEGER_FIELDS = ["start_bp", "end_bp", "duration_s", "start_time", "end_time", "ts"]


def post(client, body):
    if not isinstance(body, bytes):
        body = json.dumps(body).encode()
    return client.post(URL, content=body, headers=AUTH)


def stored(client):
    return client.get("/v1/progress", headers=AUTH).json()["documents"]


def assert_discarded(client, body):
    assert post(client, body).status_code == 202
    assert stored(client) == []


def replace(raw_field, raw_value):
    """A valid body with one field's JSON value swapped, for values json.dumps can't make."""
    fields = session() | {raw_field: "@"}
    return json.dumps(fields).replace('"@"', raw_value).encode()


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b" ",
        b"not json",
        b'{"id":',
        b"null",
        b"[]",
        b"42",
        b'"text"',
        b"\xff\xfe",
        b'{"id":"\xff"}',
        b"\xc0\xaf",
        json.dumps(session()).encode("utf-16"),
        b"\xef\xbb\xbf" + json.dumps(session()).encode(),
        b"[" * 1000,
        b'{"a":' * 200,
        TEMPLATE,
        replace("unknown", "NaN"),
        replace("unknown", "Infinity"),
    ],
)
def test_malformed_bodies_get_202_and_are_discarded(client, body):
    assert_discarded(client, body)


@pytest.mark.parametrize("field", FIELDS)
def test_missing_field_is_discarded(client, field):
    event = session()
    del event[field]
    assert_discarded(client, event)


@pytest.mark.parametrize("field", INTEGER_FIELDS)
@pytest.mark.parametrize(
    "raw",
    [
        "true",
        "false",
        "null",
        "1793520000.0",
        "1e3",
        '"4523"',
        "[]",
        "{}",
        str(2**53),
        "1" + "0" * 900,
        "-1" + "0" * 900,
    ],
)
def test_non_integers_and_huge_integers_are_discarded(client, field, raw):
    assert_discarded(client, replace(field, raw))


@pytest.mark.parametrize(
    "overrides",
    [
        {"start_bp": -1},
        {"start_bp": 10001},
        {"end_bp": -1},
        {"end_bp": 10001},
        {"duration_s": -1},
        {"start_time": 0, "end_time": 0},
        {"start_time": -5, "end_time": 5},
        {"end_time": 1793519999},
        {"ts": -1},
    ],
    ids=str,
)
def test_out_of_range_values_are_discarded(client, overrides):
    assert_discarded(client, session(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": 7},
        {"id": None},
        {"id": ""},
        {"id": "3FA9C21B-7"},
        {"id": "3fa9c21b"},
        {"id": "3fa9c21-7"},
        {"id": "3fa9c21b-"},
        {"id": "3fa9c21b-7\n"},
        {"id": "3fa9c21b-٧"},
        {"id": "{event.id}"},
        {"document": 7},
        {"document": DOCUMENT[:-1]},
        {"document": DOCUMENT + "0"},
        {"document": DOCUMENT.upper()},
        {"document": DOCUMENT + "\n"},
        {"document": "{event.document}"},
    ],
    ids=repr,
)
def test_bad_strings_are_discarded(client, overrides):
    assert_discarded(client, session(**overrides))


def test_lone_surrogate_in_a_string_is_discarded(client):
    assert_discarded(client, replace("id", r'"\ud800-7"'))
    assert_discarded(client, replace("document", r'"\ud800"'))


@pytest.mark.parametrize(
    "overrides",
    [
        {"start_bp": 0, "end_bp": 0},
        {"start_bp": 10000, "end_bp": 10000},
        {"duration_s": 0},
        {"ts": 0},
        {"start_time": 1, "end_time": 1},
        {"end_time": MAX_INT, "duration_s": MAX_INT, "ts": MAX_INT},
        {"id": "00000000-0"},
        {"id": "ffffffff-4294967295"},
        {"unknown": "ignored", "book": [1, 2.5, None, {"deep": True}]},
    ],
    ids=str,
)
def test_boundary_values_are_accepted(client, overrides):
    assert post(client, session(**overrides)).status_code == 204
    assert len(stored(client)) == 1


def sized(size):
    """A valid event padded with an unknown field to exactly `size` bytes."""
    empty_padding = len(json.dumps(session(pad="")).encode())
    body = json.dumps(session(pad="x" * (size - empty_padding))).encode()
    assert len(body) == size
    return body


def test_exactly_1_kb_is_accepted(client):
    assert post(client, sized(1024)).status_code == 204
    assert len(stored(client)) == 1


def test_over_1_kb_is_discarded(client):
    assert_discarded(client, sized(1025))


def test_cap_applies_to_chunked_bodies_that_declare_no_length(client):
    body = sized(5000)
    chunks = (body[start : start + 100] for start in range(0, len(body), 100))
    assert client.post(URL, content=chunks, headers=AUTH).status_code == 202
    assert stored(client) == []


def test_cap_applies_when_content_length_understates_the_body(client):
    headers = AUTH | {"Content-Length": "10"}
    assert client.post(URL, content=sized(5000), headers=headers).status_code == 202
    assert stored(client) == []


def test_reading_stops_soon_after_the_cap(app):
    chunk = {"type": "http.request", "body": b"x" * 100, "more_body": True}
    status, reads = call(
        app,
        path=URL,
        headers=[(b"authorization", AUTH["Authorization"].encode())],
        receive_messages=[chunk] * 1000,
    )
    assert status == 202
    assert reads <= 11


def test_client_vanishing_mid_body_is_not_a_server_error(app):
    status, _ = call(
        app,
        path=URL,
        headers=[(b"authorization", AUTH["Authorization"].encode())],
        receive_messages=[{"type": "http.request", "body": b"{", "more_body": True}],
    )
    assert status == 202


def test_a_replayed_id_keeps_the_first_copy(client):
    assert post(client, session(end_bp=4523)).status_code == 204
    assert post(client, session(end_bp=9000, end_time=1793529999)).status_code == 204

    assert [row["end_bp"] for row in stored(client)] == [4523]


def test_each_discard_is_logged_with_a_reason(client, caplog):
    with caplog.at_level(logging.INFO, logger="progress_endpoint"):
        post(client, session(end_bp=10001))
        post(client, sized(1025))

    reasons = [getattr(record, "reason", None) for record in caplog.records]
    assert any(reason and "end_bp" in reason for reason in reasons)
    assert any(reason and "1 KB" in reason for reason in reasons)


def test_the_token_is_never_logged(client, caplog):
    with caplog.at_level(logging.DEBUG):
        post(client, session())
        post(client, b"not json")
        post(client, json.dumps(session(leak=API_KEY)).encode()[:-1])
        client.post(URL, content=b"{}", headers={"Authorization": f"Bearer {API_KEY}x"})
        client.get("/v1/progress", headers=AUTH)

    logged = "".join(str(vars(record)) for record in caplog.records)
    assert API_KEY not in logged
