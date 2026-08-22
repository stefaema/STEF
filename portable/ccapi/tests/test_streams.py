"""Reopening a stream left running by an earlier run."""

from __future__ import annotations

import pytest

from portable.ccapi import InvalidStateError
from portable.ccapi.tests import fake


def test_a_live_view_stream_left_behind_is_torn_down_and_reopened():
    client, body = fake.connected()
    body.live_view_open = True

    client.live_view.start()

    assert body.live_view_open
    assert client.live_view.started_by_us


def test_a_live_view_stream_we_are_already_reading_is_not_torn_down():
    client, _ = fake.connected()
    client.live_view.start()

    with pytest.raises(InvalidStateError, match="Already started"):
        client.live_view.start()


def test_a_monitoring_stream_left_behind_is_torn_down_and_reopened():
    client, body = fake.connected()
    body.monitoring_open = True

    client.events.start_watching()

    assert body.monitoring_open
    assert client.events.watched_by_us


def test_a_monitoring_stream_we_are_already_reading_is_not_torn_down():
    client, _ = fake.connected()
    client.events.start_watching()

    with pytest.raises(InvalidStateError, match="Already started"):
        client.events.start_watching()


def test_watching_hands_back_a_live_feed_after_clearing_a_stale_stream():
    client, body = fake.connected()
    body.monitoring_open = True

    with client.events.watching() as feed:
        assert feed.latest is not None

    assert not body.monitoring_open
