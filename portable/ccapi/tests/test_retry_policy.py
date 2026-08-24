"""What a caller may change about retrying, and what the change must not cost."""

from __future__ import annotations

from portable.ccapi.tests import fake


def test_the_policy_goes_back_to_what_it_was():
    client, _ = fake.connected()
    link = client.link
    was = (link.retries, link.backoff)

    with link.retrying(retries=0, backoff=0.02):
        assert link.retries == 0
        assert link.backoff == 0.02

    assert (link.retries, link.backoff) == was


def test_a_nested_override_restores_the_one_around_it():
    client, _ = fake.connected()
    link = client.link
    outer = link.retries

    with link.retrying(retries=1):
        with link.retrying(retries=0):
            assert link.retries == 0
        assert link.retries == 1

    assert link.retries == outer


def test_asking_for_one_number_leaves_the_other_alone():
    client, _ = fake.connected()
    link = client.link
    backoff = link.backoff

    with link.retrying(retries=0):
        assert link.backoff == backoff


def test_a_new_policy_costs_no_reconnection():
    client, _ = fake.connected()
    link = client.link
    client.filesystem.storages()
    session = link._transport

    with link.retrying(retries=0, backoff=0.02):
        client.filesystem.storages()
        assert link._transport is session

    assert link._transport is session
    assert link.up
