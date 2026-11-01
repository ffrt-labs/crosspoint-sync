# Progress endpoint API

Contract between the `home-sync` SD plugin and the home progress endpoint. It is shaped
by the firmware's plugin-event behaviour, described in CrossPoint's
[`docs/plugin-events.md`](https://github.com/crosspoint-reader/crosspoint-reader/blob/develop/docs/plugin-events.md).

## Why the response policy looks odd

The firmware delivers events at-least-once and in order, and stops draining at the first
non-2xx response. An event the server rejects forever would block every later event until
the 4 KB outbox overflows and is dropped wholesale. So the server answers 2xx for anything
a retry cannot fix, and uses a failing status only for what a retry or a fix can resolve.

## `POST /v1/events/reader-session`

Headers:

- `Authorization: Bearer <key>`
- `Content-Type: application/json`

The plugin's body template:

```json
{"id":"{event.id}","document":"{event.document}","start_bp":{event.start_progress_bp},"end_bp":{event.end_progress_bp},"duration_s":{event.duration_seconds},"start_time":{event.start_time},"end_time":{event.end_time},"ts":{event.ts}}
```

The book path is deliberately absent. Firmware substitutes values unescaped, so a `"` in
a filename would break the JSON.

Example of a delivered body:

```json
{"id":"3fa9c21b-7","document":"0123456789abcdef0123456789abcdef","start_bp":4100,"end_bp":4523,"duration_s":754,"start_time":1793520000,"end_time":1793520754,"ts":1793521200}
```

### Fields

| Field | Type | Rule |
|---|---|---|
| `id` | string | `^[0-9a-f]{8}-[0-9]+$`, the firmware's `%08lx-%lu`. Dedupe key. |
| `document` | string | `^[0-9a-f]{32}$`, binary KOSync partial MD5. |
| `start_bp`, `end_bp` | integer | 0..10000. |
| `duration_s` | integer | 0 or more. |
| `start_time` | integer | Greater than 0, Unix seconds. |
| `end_time` | integer | At least `start_time`. |
| `ts` | integer | 0 or more. Firmware sends 0 if the clock was never set. |

Every integer must be a JSON integer no greater than 2^53 - 1. Unknown fields are ignored.

### Responses

| Case | Status |
|---|---|
| Accepted | 204 |
| Duplicate `id` (at-least-once replay); the first copy wins | 204 |
| Authenticated but malformed or out of range, logged and discarded | 202 |
| Authenticated but over 1 KB, logged and discarded | 202 |
| Bad or missing token. The queue stalls until this is fixed, which is intended. | 401 |
| Server fault, such as a database error. The event retries on the next drain. | 5xx |

Authentication is checked before the body is read. "Malformed" covers everything the body
can do wrong: invalid JSON, non-object JSON, invalid UTF-8, missing fields, wrong types,
and the literal `{event.x}` text firmware sends for a variable it could not substitute.

The firmware counts a 202 as delivered, so the device shows the "Progress synced" toast
for a discarded event. The server log is the only record of the discard.

## Semantics

- Every session row is kept, which gives a reading history for free.
- The latest position for a document is the row with the greatest `end_time`, not the
  greatest progress. Ties go to the greater `ts`, then to the most recently received row.
- Paging or jumping backwards does not move the position back by itself. Firmware clamps
  `end_progress_bp` so it never falls within a session, and reverse turns and chapter
  skips do not count. The position moves back only through a later qualifying session
  with forward turns that ends earlier in the book.
- `end_time` is **not** when reading stopped. Firmware removes idle gaps, so it is always
  `start_time + duration_seconds` and can be earlier than the real stop time. It still
  orders sessions correctly, because each session starts after the previous one really
  ended. Use `ts`, the emission time, to display when a book was last read.
- Progress is `end_bp / 10000`.

## Read API

Both routes use the same bearer auth. A bad or missing token gets 401.

### `GET /v1/progress`

Latest position per document, most recently read first.

```json
{"documents":[{"document":"0123456789abcdef0123456789abcdef","progress":0.4523,"end_bp":4523,"end_time":1793520754,"ts":1793521200,"received_at":1793521201}]}
```

### `GET /v1/progress/{document}`

The same object for one document, or 404 if the document has no sessions.

## `GET /healthz`

Unauthenticated, for container healthchecks. Returns 200 with `{"status":"ok"}` when the
database can be read and written, 503 otherwise. The write check is rolled back, so it
stores nothing.
