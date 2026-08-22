"""Storage counts and path handling in listings."""

from __future__ import annotations

import pytest

from portable.ccapi import Endpoint, FileType, StorageError
from portable.ccapi.tests import fake


@pytest.fixture
def camera():
    """Return a client connected to the fake camera."""
    client, _ = fake.connected()
    return client


def test_the_current_card_reports_the_counts_from_the_storage_endpoint(camera):
    found = camera.filesystem.current()

    assert found.file_count == 3
    assert found.capacity == 128_000_000_000
    assert found.free == 96_000_000_000


def test_the_current_card_is_the_one_the_camera_names(camera):
    assert camera.filesystem.current().name == fake.CARD


def test_reading_the_count_asks_the_endpoint_that_answers_it(camera):
    camera.filesystem.file_count

    asked = [path for _, path in camera.link._transport.camera.asked]
    assert any(one.endswith(Endpoint.STORAGE) for one in asked)


def test_a_card_the_camera_writes_to_but_does_not_list_is_refused():
    client, body = fake.connected()
    body.storages = lambda: {"storagelist": []}

    with pytest.raises(StorageError, match="does not list"):
        client.filesystem.current()


def test_listing_takes_the_full_path_a_listing_returned(camera):
    volumes = camera.filesystem.volumes()
    directories = camera.filesystem.directories(volumes[0])

    assert camera.filesystem.files_in(directories[0])


def test_counting_takes_the_full_path_a_listing_returned(camera):
    directory = camera.filesystem.current_directory()

    assert camera.filesystem.count(directory, FileType.ALL) == 3


def test_a_full_path_is_never_joined_onto_the_prefix_it_already_carries(camera):
    camera.filesystem.files_in(camera.filesystem.current_directory())

    asked = [path for _, path in camera.link._transport.camera.asked]
    assert not any(one.count("/contents") > 1 for one in asked)


def test_a_bare_volume_name_lists_too(camera):
    assert camera.filesystem.directories(fake.CARD)


def test_walking_reaches_every_file_on_the_card(camera):
    found = list(camera.filesystem.walk(camera.filesystem.current_directory()))

    assert len(found) == 3
