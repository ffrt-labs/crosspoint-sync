"""Drives the app with a hand-fed ASGI request.

TestClient hands the app the whole body up front. These tests need to control delivery:
to see whether the app reads the body at all, and to disconnect partway through it.
"""

import anyio


def call(app, *, path, headers=(), method="POST", receive_messages=()):
    """Returns (status, number of receive() calls made by the app)."""
    pending = list(receive_messages)
    received = 0
    statuses = []

    async def receive():
        nonlocal received
        received += 1
        return pending.pop(0) if pending else {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            statuses.append(message["status"])

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 1),
        "headers": list(headers),
    }
    anyio.run(app, scope, receive, send)
    return statuses[0], received
