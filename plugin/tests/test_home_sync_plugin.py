"""Device-free checks of the home-sync SD plugin against firmware behaviour.

The firmware facts below come from CrossPoint's src/util/PluginEvents.cpp,
src/util/PluginHttp.cpp and docs/plugin-events.md.
"""

import json
import re
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "home-sync"

MAX_MANIFEST_BYTES = 8 * 1024
MAX_CONFIG_BYTES = 2 * 1024
MAX_FOLDER_NAME_BYTES = 23
MAX_FOLDER_PATH_BYTES = 63
MAX_EVENT_LINE_BYTES = 512
PLUGIN_ROOTS = ["/.crosspoint/plugins", "/plugins", "/.plugins"]


def load_manifest():
    return json.loads((PLUGIN_DIR / "device.json").read_text(encoding="utf-8"))


def reader_session_handler():
    return load_manifest()["events"]["reader.session"]


def test_manifest_fits_the_firmware_read_cap():
    assert (PLUGIN_DIR / "device.json").stat().st_size < MAX_MANIFEST_BYTES


def test_reader_session_is_a_request_handler_that_connects_at_sleep():
    handler = reader_session_handler()

    assert handler["connect"] is True
    assert handler["request"]["method"] == "POST"
    assert handler["request"]["url"] == "{cfg.server}/v1/events/reader-session"
    assert handler["request"]["headers"] == {
        "Authorization": "Bearer {cfg.key}",
        "Content-Type": "application/json",
    }
    # A "download" key would turn this into a streamed fetch; "require_meta"
    # would stop events for books without a sidecar from being queued.
    assert "download" not in handler
    assert "require_meta" not in handler


def test_manifest_points_at_a_relative_config_file():
    assert load_manifest()["config"] == {"file": "config.json"}


def substitute_all(text, key, value):
    return text.replace(key, value)


def drain_substituted(template, config, event):
    """Port of drainSubstituted() in PluginEvents.cpp, without {meta.*}.

    Values go in unescaped and anything unmatched stays as literal text. The
    manifest declares no token file, so {token} becomes the empty string.
    """
    result = substitute_all(template, "{token}", "")
    for key, value in config.items():
        result = substitute_all(result, "{cfg." + key + "}", value)
    result = substitute_all(result, "{event.ts}", str(event["ts"]))
    result = substitute_all(result, "{event.id}", event["id"])
    for key, value in event["vars"].items():
        result = substitute_all(result, "{event." + key + "}", value)
    return result


# One queued line as emit() writes it. All vars are strings, per the
# reader.session contract in plugin-events.md. Values match the delivered-body
# example in docs/api.md.
SAMPLE_EVENT = {
    "id": "3fa9c21b-7",
    "ts": 1793521200,
    "vars": {
        "book": '/Books/A "quoted" title.epub',
        "document": "0123456789abcdef0123456789abcdef",
        "start_time": "1793520000",
        "end_time": "1793520754",
        "duration_seconds": "754",
        "start_progress_bp": "4100",
        "end_progress_bp": "4523",
        "progress_scale": "10000",
    },
}

CONTRACT_EXAMPLE_BODY = {
    "id": "3fa9c21b-7",
    "document": "0123456789abcdef0123456789abcdef",
    "start_bp": 4100,
    "end_bp": 4523,
    "duration_s": 754,
    "start_time": 1793520000,
    "end_time": 1793520754,
    "ts": 1793521200,
}


def test_rendered_body_is_exactly_the_contract_example():
    template = reader_session_handler()["request"]["body"]

    rendered = drain_substituted(template, {}, SAMPLE_EVENT)

    assert json.loads(rendered) == CONTRACT_EXAMPLE_BODY


def test_body_template_is_the_one_in_the_api_contract():
    template = reader_session_handler()["request"]["body"]
    api_doc = PLUGIN_DIR.parents[1] / "docs" / "api.md"

    assert template in api_doc.read_text(encoding="utf-8").splitlines()


def test_body_leaves_out_the_book_path():
    template = reader_session_handler()["request"]["body"]

    assert "{event.book}" not in template


def handler_templates():
    handler = reader_session_handler()
    request = handler["request"]
    return [
        request["url"],
        request["body"],
        handler["toast"],
        *request["headers"].values(),
    ]


def template_variables():
    return {
        name for text in handler_templates() for name in re.findall(r"\{([a-z_.]+)\}", text)
    }


def load_example_config():
    return json.loads((PLUGIN_DIR / "config.example.json").read_text(encoding="utf-8"))


def test_every_cfg_variable_exists_in_the_example_config():
    used = {name.removeprefix("cfg.") for name in template_variables() if name.startswith("cfg.")}

    assert used == {"server", "key"}
    assert used <= load_example_config().keys()


def test_example_config_is_flat_strings_within_the_firmware_cap():
    # loadConfigFile() turns anything but strings and integers into "".
    assert all(isinstance(value, str) for value in load_example_config().values())
    assert (PLUGIN_DIR / "config.example.json").stat().st_size <= MAX_CONFIG_BYTES


def test_every_variable_is_one_the_firmware_substitutes():
    known = {"event.ts", "event.id"}
    known |= {"event." + name for name in SAMPLE_EVENT["vars"]}
    known |= {"cfg." + name for name in load_example_config()}

    assert template_variables() <= known


def test_url_and_headers_render_without_leftover_variables():
    config = {"server": "http://192.168.1.10:8000", "key": "sample-key"}
    request = reader_session_handler()["request"]

    url = drain_substituted(request["url"], config, SAMPLE_EVENT)
    authorization = drain_substituted(request["headers"]["Authorization"], config, SAMPLE_EVENT)

    assert url == "http://192.168.1.10:8000/v1/events/reader-session"
    assert authorization == "Bearer sample-key"


def test_folder_name_fits_the_subscription_table():
    assert len(PLUGIN_DIR.name.encode()) <= MAX_FOLDER_NAME_BYTES


@pytest.mark.parametrize("root", PLUGIN_ROOTS)
def test_folder_path_fits_the_subscription_table(root):
    assert len(f"{root}/{PLUGIN_DIR.name}".encode()) <= MAX_FOLDER_PATH_BYTES


def test_example_config_key_is_a_placeholder():
    assert load_example_config()["key"].startswith("<")


def test_book_path_limit_in_the_readme_survives_the_event_line_cap():
    # Longest values the firmware can queue for a session, with the book path
    # at the limit the README promises. emit() counts the trailing newline.
    limit = int(re.search(r"Book path limit: (\d+) bytes", readme_text()).group(1))
    line = {
        "e": "reader.session",
        "id": "ffffffff-4294967295",
        "ts": 1793521200,
        "vars": {
            **SAMPLE_EVENT["vars"],
            "book": "x" * limit,
            "end_time": "1793521800",
            "duration_seconds": "180000",
            "start_progress_bp": "10000",
            "end_progress_bp": "10000",
        },
    }

    assert len(json.dumps(line, separators=(",", ":"))) + 1 <= MAX_EVENT_LINE_BYTES


def readme_text():
    return (PLUGIN_DIR / "README.md").read_text(encoding="utf-8")


def test_readme_fits_the_on_device_viewer():
    assert (PLUGIN_DIR / "README.md").stat().st_size <= 16 * 1024
