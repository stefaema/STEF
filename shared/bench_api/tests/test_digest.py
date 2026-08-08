"""A digest, and the boundary it has to cross as JSON."""

import dataclasses
import json

from shared.bench_api import Button, Digest, Layer, Span

DATAGRAM = Layer(
    title="Datagram",
    body=bytes.fromhex("05000048c1"),
    legend=(Span("sync", 0, 1), Span("addr", 1, 1), Span("data", 2, 3)),
    buttons=(
        Button(label="Send datagram", call="relay.send(idx=0, tx=...)", hazardous=True),
    ),
)

REQUEST = Layer(
    title="Request payload",
    body=bytes.fromhex("00000000"),
    legend=(Span("idx", 0, 1), Span("_pad", 1, 3)),
    editable=True,
)


def as_json(digest):
    """Return the digest the way the backend hands it to the browser."""

    def plain(value):
        if isinstance(value, bytes):
            return value.hex()
        raise TypeError(value)

    return json.dumps(dataclasses.asdict(digest), default=plain)


def test_a_digest_keeps_its_layers_outermost_first():
    digest = Digest(layers=(REQUEST, DATAGRAM))
    assert [layer.title for layer in digest.layers] == ["Request payload", "Datagram"]


def test_a_button_stays_attached_to_the_layer_it_acts_on():
    digest = Digest(layers=(REQUEST, DATAGRAM))
    assert digest.layers[0].buttons == ()
    assert digest.layers[1].buttons[0].label == "Send datagram"
    # Capability is declared, never inferred: an inner layer exists here, and
    # that on its own says nothing about what may be sent.
    assert digest.buttons == ()


def test_a_digest_round_trips_through_the_shape_that_crosses_the_boundary():
    digest = Digest(
        layers=(REQUEST, DATAGRAM),
        buttons=(Button(label="Send all", call="raw.write(...)", closes=True),),
    )
    back = json.loads(as_json(digest))

    assert [layer["title"] for layer in back["layers"]] == [
        "Request payload",
        "Datagram",
    ]
    assert back["layers"][1]["buttons"][0] == {
        "label": "Send datagram",
        "call": "relay.send(idx=0, tx=...)",
        "hazardous": True,
        "closes": False,
    }
    assert back["layers"][1]["body"] == "05000048c1"
    assert back["buttons"][0]["closes"] is True


def test_a_legend_names_every_run_of_bytes_including_the_padding():
    # How a span is drawn is the GUI's. The contract only has to name it.
    assert [span.name for span in REQUEST.legend] == ["idx", "_pad"]
    assert sum(span.length for span in REQUEST.legend) == len(REQUEST.body)


def test_a_producer_takes_values_and_no_link(rig):
    write = rig.actions["raw.write"]
    assert write.digest is not None

    produced = write.digest({"idx": 2, "ops": [1, 2, 3]})
    assert isinstance(produced, Digest)
    assert produced.layers[0].body == bytes([2, 3])


def test_an_action_without_a_digest_says_so(rig):
    assert rig.actions["raw.read"].digest is None
