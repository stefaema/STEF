"""Which endpoints a plain GET must not be pointed at."""

from __future__ import annotations

from portable.ccapi import STREAMED, Endpoint


def test_the_push_event_stream_is_named_as_one():
    assert Endpoint.MONITORING in STREAMED


def test_nothing_that_answers_promptly_is_named_as_a_stream():
    assert Endpoint.BATTERY not in STREAMED
    assert Endpoint.STORAGE not in STREAMED
