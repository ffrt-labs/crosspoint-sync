"""The reader-session event: parsing and validation of a delivered body."""

import json
import re
from dataclasses import dataclass
from typing import NoReturn

MAX_INTEGER = 2**53 - 1
MAX_BP = 10000
ID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9]+")
DOCUMENT_PATTERN = re.compile(r"[0-9a-f]{32}")


class InvalidEvent(ValueError):
    """The body can never be stored. The message names the rule, never the client's data."""


@dataclass(frozen=True)
class ReaderSession:
    id: str
    document: str
    start_bp: int
    end_bp: int
    duration_s: int
    start_time: int
    end_time: int
    ts: int


def is_document(value: object) -> bool:
    return isinstance(value, str) and DOCUMENT_PATTERN.fullmatch(value) is not None


def _reject_constant(name: str) -> NoReturn:
    raise ValueError(f"{name} is not JSON")


def _decode(body: bytes) -> object:
    try:
        # Decoded here because json.loads(bytes) would also accept UTF-16 and UTF-32.
        return json.loads(body.decode("utf-8"), parse_constant=_reject_constant)
    except UnicodeDecodeError:
        raise InvalidEvent("invalid UTF-8") from None
    except (ValueError, RecursionError):
        raise InvalidEvent("invalid JSON") from None


def _integer(fields: dict, name: str, minimum: int = 0, maximum: int = MAX_INTEGER) -> int:
    value = fields.get(name)
    if type(value) is not int:  # bool is a subclass of int
        raise InvalidEvent(f"{name} is not an integer")
    if not minimum <= value <= maximum:
        raise InvalidEvent(f"{name} is out of range")
    return value


def parse_session(body: bytes) -> ReaderSession:
    fields = _decode(body)
    if not isinstance(fields, dict):
        raise InvalidEvent("body is not an object")

    event_id = fields.get("id")
    if not isinstance(event_id, str) or ID_PATTERN.fullmatch(event_id) is None:
        raise InvalidEvent("id is invalid")
    document = fields.get("document")
    if not is_document(document):
        raise InvalidEvent("document is invalid")

    start_time = _integer(fields, "start_time", minimum=1)
    return ReaderSession(
        id=event_id,
        document=document,
        start_bp=_integer(fields, "start_bp", maximum=MAX_BP),
        end_bp=_integer(fields, "end_bp", maximum=MAX_BP),
        duration_s=_integer(fields, "duration_s"),
        start_time=start_time,
        end_time=_integer(fields, "end_time", minimum=start_time),
        ts=_integer(fields, "ts"),
    )
