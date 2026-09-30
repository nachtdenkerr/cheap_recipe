"""logging_setup: the terminal plus a log file that can be read afterwards."""

import logging

import pytest

from cheaprecipe.logging_setup import setup_logging


@pytest.fixture
def restore_root_logger():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    for handler in root.handlers:
        if handler not in handlers:
            handler.close()
    root.handlers[:] = handlers
    root.setLevel(level)


def test_agent_steps_reach_the_log_file(tmp_path, restore_root_logger):
    path = setup_logging("INFO", log_file=tmp_path / "logs" / "cheaprecipe.log")
    logging.getLogger("cheaprecipe.agents.loop").info("round 1/3: planned ['Soup'] — critic passed")
    logging.getLogger("httpx").info("HTTP Request: POST https://openrouter.ai")  # quietened

    text = path.read_text(encoding="utf-8")
    assert "INFO    cheaprecipe.agents.loop: round 1/3: planned ['Soup']" in text
    assert "openrouter" not in text


def test_setting_up_twice_does_not_double_lines(tmp_path, restore_root_logger):
    path = tmp_path / "cheaprecipe.log"
    setup_logging("INFO", log_file=path)
    setup_logging("INFO", log_file=path)  # the API's lifespan runs again under --reload
    logging.getLogger("cheaprecipe").info("once")
    assert path.read_text(encoding="utf-8").count("once") == 1


def test_no_file_when_turned_off(tmp_path, restore_root_logger):
    assert setup_logging("INFO", log_file=None) is None
