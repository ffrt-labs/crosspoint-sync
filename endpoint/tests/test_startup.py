import json
import logging
from pathlib import Path

import pytest

from progress_endpoint.config import Config, ConfigError
from progress_endpoint.logs import JsonFormatter


@pytest.mark.parametrize("env", [{}, {"PROGRESS_API_KEY": ""}, {"PROGRESS_API_KEY": " \n"}])
def test_refuses_to_start_without_a_key(env):
    with pytest.raises(ConfigError):
        Config.from_env(env)


def test_db_path_defaults_under_data():
    assert Config.from_env({"PROGRESS_API_KEY": "k"}).db_path == Path("/data/progress.db")


def test_db_path_comes_from_the_environment():
    env = {"PROGRESS_API_KEY": "k", "PROGRESS_DB_PATH": "/tmp/elsewhere.db"}
    assert Config.from_env(env).db_path == Path("/tmp/elsewhere.db")


def test_a_trailing_newline_is_not_part_of_the_key():
    assert Config.from_env({"PROGRESS_API_KEY": "k\n"}).api_key == "k"


def test_log_lines_are_json_with_the_extra_fields():
    record = logging.makeLogRecord(
        {"msg": "event_discarded", "levelname": "WARNING", "reason": "id is invalid"}
    )

    line = json.loads(JsonFormatter().format(record))
    assert line["event"] == "event_discarded"
    assert line["level"] == "WARNING"
    assert line["reason"] == "id is invalid"
    assert "time" in line
