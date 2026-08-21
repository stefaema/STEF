"""What a line looks like, what is kept, and what the standard library does."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import pytest

from shared import logs


@pytest.fixture
def written(tmp_path: Path):
    """Return a sink that collects rendered lines, and take it down afterwards."""
    lines: list[str] = []
    logs.logger.remove()
    logs.logger.configure(extra=dict(logs.DEFAULTS))
    logs.logger.add(lines.append, format=logs.template_for, level="DEBUG")
    yield lines
    logs.logger.remove()


# ── The shape of one line ────────────────────────────────────────────────────


def test_a_line_names_its_level_time_and_component_in_that_order(written):
    logs.component("transport.prelink").warning("open load")

    head, _, message = written[0].partition("] ")
    assert head == "[WARNING "
    assert "[transport.prelink   ]" in written[0]
    assert message.rstrip().endswith("open load")


def test_every_level_leaves_the_message_in_the_same_column(written):
    logs.component("a.b").debug("one")
    logs.component("a.b").critical("two")

    columns = {line.index("] ", line.index("[a.b")) for line in written}
    assert len(columns) == 1


def test_a_component_that_was_never_bound_still_renders(written):
    logs.logger.info("nobody said who")
    assert f"[{logs.DEFAULT_COMPONENT: <20}]" in written[0]


# ── What is kept ─────────────────────────────────────────────────────────────


def _archive(where: Path, name: str, size: int, age: float) -> Path:
    made = where / name
    made.write_bytes(b"x" * size)
    os.utime(made, (age, age))
    return made


def test_retention_drops_the_oldest_once_the_budget_is_passed(tmp_path):
    now = time.time()
    old = _archive(tmp_path, "old.zip", 100, now - 300)
    middle = _archive(tmp_path, "middle.zip", 100, now - 200)
    new = _archive(tmp_path, "new.zip", 100, now - 100)

    logs.keep_under(150)([str(old), str(middle), str(new)])

    assert new.exists()
    assert not middle.exists()
    assert not old.exists()


def test_the_newest_survives_even_when_it_alone_passes_the_budget(tmp_path):
    only = _archive(tmp_path, "only.zip", 500, time.time())

    logs.keep_under(10)([str(only)])

    assert only.exists()


# ── Lines written to the standard library ────────────────────────────────────


def test_a_standard_library_record_arrives_named_for_its_logger(written):
    logs.intercept_stdlib()
    logging.getLogger("ccapi.link").error("the camera is not connected")

    assert "[ERROR   ]" in written[0]
    assert "[ccapi.link" in written[0]
    assert written[0].rstrip().endswith("the camera is not connected")


def test_a_standard_library_level_keeps_its_severity(written):
    logs.intercept_stdlib()
    logging.getLogger("ccapi").warning("retrying")

    assert "[WARNING " in written[0]


def test_what_a_caller_attached_travels_with_the_line(written):
    logs.intercept_stdlib()
    logging.getLogger("ccapi.link").info("refused", extra={"status": 503})

    assert written[0].record["extra"]["status"] == 503


def test_a_record_s_own_attributes_are_not_mistaken_for_what_was_attached(written):
    logs.intercept_stdlib()
    logging.getLogger("ccapi.link").info("connecting")

    attached = set(written[0].record["extra"])
    assert attached == {"component", "routine"}


def test_a_caller_may_name_the_component_without_colliding_with_the_one_derived(
    written,
):
    logs.intercept_stdlib()
    logging.getLogger("urllib3").info("GET", extra={"component": "ccapi.link"})

    assert written[0].record["extra"]["component"] == "ccapi.link"


# ── The file it all lands in ─────────────────────────────────────────────────


def test_the_file_is_one_json_object_per_line_carrying_its_own_rendered_text(tmp_path):
    written = logs.start(directory=tmp_path, console_level=None)
    logs.component("capture").info("connected to {}", "192.168.1.2")
    logs.logger.remove()

    (line,) = written.read_text().splitlines()
    loaded = json.loads(line)
    assert loaded["record"]["extra"]["component"] == "capture"
    assert loaded["text"].rstrip().endswith("connected to 192.168.1.2")


def test_a_field_no_json_encoder_knows_still_reaches_the_file(tmp_path):
    logs.intercept_stdlib()
    written = logs.start(directory=tmp_path, console_level=None)
    logging.getLogger("ccapi.link").info("read", extra={"at": Path("/dev/ttyACM0")})
    logs.logger.remove()

    (line,) = written.read_text().splitlines()
    assert json.loads(line)["record"]["extra"]["at"] == "/dev/ttyACM0"
