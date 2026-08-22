"""Which endpoints must be requested as streams."""

from __future__ import annotations

from portable.ccapi import STREAMED, Endpoint


def test_the_push_event_stream_is_listed_as_streamed():
    assert Endpoint.MONITORING in STREAMED


def test_endpoints_that_answer_promptly_are_not_listed_as_streamed():
    assert Endpoint.BATTERY not in STREAMED
    assert Endpoint.STORAGE not in STREAMED
