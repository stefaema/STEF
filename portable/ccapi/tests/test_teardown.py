"""Disconnecting stops what the session started."""

from __future__ import annotations

from portable.ccapi import DeviceBusyError, LinkState
from portable.ccapi.tests import fake


def test_disconnecting_stops_a_recording_we_started():
    client, body = fake.connected()
    client.movie.enter_movie_mode()
    client.movie.start_recording()

    client.disconnect()

    assert not body.recording


def test_disconnecting_leaves_a_recording_we_did_not_start_alone():
    client, body = fake.connected()
    body.recording = True

    client.disconnect()

    assert body.recording


def test_disconnecting_stops_a_live_view_stream_we_started():
    client, body = fake.connected()
    client.live_view.start()

    client.disconnect()

    assert not body.live_view_open


def test_disconnecting_stops_a_monitoring_stream_we_started():
    client, body = fake.connected()
    client.events.start_watching()

    client.disconnect()

    assert not body.monitoring_open


def test_a_teardown_the_camera_refuses_still_lets_the_disconnect_finish(monkeypatch):
    client, _ = fake.connected()
    client.movie.enter_movie_mode()
    client.movie.start_recording()

    def refuse() -> None:
        raise DeviceBusyError("503: Device busy", 503)

    monkeypatch.setattr(client.movie, "stop_recording", refuse)

    client.disconnect()

    assert client.link.state is LinkState.DOWN


def test_leaving_the_context_manager_stops_what_it_started():
    client, body = fake.connected()

    with client:
        client.live_view.start()

    assert not body.live_view_open
