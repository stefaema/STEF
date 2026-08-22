"""Entering movie mode, which lags its acknowledgement."""

from __future__ import annotations

import pytest

from portable.ccapi import InvalidStateError
from portable.ccapi.tests import fake


def test_entering_returns_only_once_the_camera_agrees_it_is_there():
    client, _ = fake.connected(fake.Camera(mode_lag=3))

    client.movie.enter_movie_mode()

    assert client.movie.in_movie_mode()


def test_recording_starts_after_a_mode_that_took_a_moment_to_arrive():
    client, body = fake.connected(fake.Camera(mode_lag=3))

    with client.movie.mode():
        with client.movie.recording():
            assert body.recording

    assert not client.movie.in_movie_mode()


def test_a_mode_that_never_arrives_raises_instead_of_recording(
    monkeypatch,
):
    from portable.ccapi import movie

    monkeypatch.setattr(movie, "SETTLE", 0.2)
    client, _ = fake.connected(fake.Camera(mode_lag=1000))

    with pytest.raises(InvalidStateError, match="not there"):
        client.movie.enter_movie_mode()


def test_leaving_puts_the_camera_back_in_stills():
    client, _ = fake.connected(fake.Camera(mode_lag=2))

    client.movie.enter_movie_mode()
    client.movie.leave_movie_mode()

    assert not client.movie.in_movie_mode()
