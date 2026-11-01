from conftest import AUTH, CONTRACT_BODY, DOCUMENT


def post(client):
    return client.post("/v1/events/reader-session", content=CONTRACT_BODY, headers=AUTH)


def test_contract_example_is_stored_and_replay_keeps_one_session(client):
    assert post(client).status_code == 204
    assert post(client).status_code == 204

    documents = client.get("/v1/progress", headers=AUTH).json()["documents"]
    assert len(documents) == 1
    assert documents[0]["document"] == DOCUMENT
    assert documents[0]["progress"] == 0.4523
    assert documents[0]["end_bp"] == 4523
    assert documents[0]["end_time"] == 1793520754
    assert documents[0]["ts"] == 1793521200
    assert isinstance(documents[0]["received_at"], int)
