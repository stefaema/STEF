"""The setting whose value has two axes, and what the generic pair does with it."""

from __future__ import annotations

import pytest

from portable.ccapi import Setting
from portable.ccapi.tests import fake


@pytest.fixture
def camera():
    """Return a camera linked to a body that answers like the reference."""
    client, _ = fake.connected()
    return client


def test_image_quality_reads_both_axes(camera):
    found = camera.settings.image_quality()

    assert (found.raw, found.jpeg) == ("none", "large_fine")


def test_image_quality_reads_both_lists_of_what_is_on_offer(camera):
    found = camera.settings.image_quality()

    assert found.raw_allowed == fake.RAW_ABILITY
    assert found.jpeg_allowed == fake.JPEG_ABILITY


def test_a_body_offering_a_file_on_each_axis_can_write_two(camera):
    assert camera.settings.image_quality().offers_two


def test_writing_both_axes_takes(camera):
    camera.settings.set_image_quality("craw", "large_fine")

    assert camera.settings.image_quality().writes_two


def test_one_axis_set_to_none_is_one_file_per_release(camera):
    camera.settings.set_image_quality("none", "small")
    found = camera.settings.image_quality()

    assert found.writes_jpeg
    assert not found.writes_two


# ── What the generic pair says about it ──────────────────────────────────────


def test_the_generic_reader_offers_nothing_rather_than_the_names_of_the_axes(camera):
    found = camera.settings.get(Setting.STILLIMAGEQUALITY)

    assert found.allowed == ()
    assert not found.writable


def test_a_setting_of_the_ordinary_shape_is_untouched(camera):
    found = camera.settings.get(Setting.ISO)

    assert found.value == "400"
    assert found.allowed == ("100", "200", "400")
