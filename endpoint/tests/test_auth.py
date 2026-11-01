import pytest

from asgi import call
from conftest import API_KEY, AUTH, CONTRACT_BODY, DOCUMENT

ROUTES = [
    ("POST", "/v1/events/reader-session"),
    ("GET", "/v1/progress"),
    ("GET", f"/v1/progress/{DOCUMENT}"),
]

BAD_HEADERS = {
    "missing": {},
    "wrong key": {"Authorization": "Bearer nope"},
    "empty key": {"Authorization": "Bearer "},
    "no scheme": {"Authorization": API_KEY},
    "wrong scheme": {"Authorization": f"Basic {API_KEY}"},
    "key with a suffix": {"Authorization": f"Bearer {API_KEY}x"},
    "non-ascii key": {"Authorization": "Bearer clé".encode("latin-1")},
    "invalid utf-8 key": {"Authorization": b"Bearer \xff\xfe"},
}


@pytest.mark.parametrize("method,path", ROUTES)
@pytest.mark.parametrize("headers", BAD_HEADERS.values(), ids=BAD_HEADERS.keys())
def test_bad_or_missing_token_gets_401(client, method, path, headers):
    assert client.request(method, path, headers=headers).status_code == 401


def test_good_token_passes_auth(client):
    assert client.get("/v1/progress", headers=AUTH).status_code == 200


def test_bad_token_is_rejected_without_reading_the_body(app):
    status, reads = call(
        app,
        path="/v1/events/reader-session",
        headers=[(b"authorization", b"Bearer nope")],
        receive_messages=[{"type": "http.request", "body": CONTRACT_BODY}],
    )
    assert (status, reads) == (401, 0)


def test_a_valid_event_with_a_bad_token_is_not_stored(client):
    client.post("/v1/events/reader-session", content=CONTRACT_BODY)
    assert client.get("/v1/progress", headers=AUTH).json() == {"documents": []}
