# ccapi

A client for Canon's Camera Control API: a camera is an HTTP server, and this
speaks to it.

Depends on nothing but an HTTP client, so anything that wants to drive a Canon
body can use it. It knows about cameras and about nothing else.

## Two questions about every endpoint, kept apart

A camera answers `GET /ccapi` with a manifest: every endpoint it serves, at
every API version, with the HTTP methods each accepts. So **access** is
discovered, per body, at connect. Nothing here needs to hardcode it, and a
model that lacks live view says so itself.

What the manifest never says is **who changes the value**, and that is what
decides whether an answer you already have is still true. Battery drains on its
own. ISO is whatever we last set it to. A serial number never moves. Three
different answers to "may I remember this", and no amount of reading the
manifest produces them.

So class is authored, in `TABLE`, beside the endpoint it describes:

| volatility | who writes it | example |
|---|---|---|
| `VOLATILE` | the camera, unprompted | battery, temperature, free space |
| `OWNED` | us, and nothing else | ISO, aperture, shutter speed |
| `CONSTANT` | nobody, in a given session | model, serial, firmware version |

Access discovered, volatility authored. Neither answers the other's question.

## Why volatile is not the same as uncacheable

A device that cannot tell you a value changed leaves you polling it. This one
can: `/event/polling` returns only the fields that moved since you last asked,
and `/event/monitoring` pushes them as they happen.

That makes the event stream a cache invalidator, and `CameraState` the cache it
keeps honest. Reads inside a feed are local. Outside one, there is nothing
watching, so every read is a round trip and the cache is not offered at all:

```python
with camera.events.watching():
    camera.status.temperature()     # local
camera.status.temperature()         # round trip
```

Nothing here can hand back a stale value, because the only mode that holds
values is the mode that is watching them.

## Blocks are named for what is true inside them

`connect` and `disconnect` are the two things that happen; `connection` is the
state between them. That is the rule everywhere, so a verb is always a
primitive and a noun is always a block:

| primitives | block | yields |
|---|---|---|
| `connect` / `disconnect` | `camera.connection()` | nothing |
| `enter_movie_mode` / `leave_movie_mode` | `movie.mode()` | nothing |
| `start_recording` / `stop_recording` | `movie.recording()` | nothing |
| `start_watching` / `stop_watching` | `events.watching()` | the feed |
| `start` / `stop` | `live_view.session()` | the stream |
| — | `shooting.held()` | the button |

A block yields only what exists nowhere else. `camera` is already in scope, so
`connection()` hands back nothing; a live view stream exists only while the
session does, so `session()` hands it over.

`held()` is the one with no primitives under it. A full press with no release
leaves a camera that refuses everything until someone lets go, and scoping
`press()` to the block is what makes that unspellable.

## A block restores what it found

The camera refuses a second live view with `Already started`, and a `DELETE`
against something idle with `Not started`. Both are the same mistake: a block
assuming it owns what it entered.

So every block asks first, and undoes only what it did. Entering a connection
that is already up connects nothing and disconnects nothing on the way out,
which is what lets a diagnostic routine use `camera.connection()` without
hanging up on the operator who connected by hand.

`shooting.held()` is the exception and always releases. A held shutter has no
readback and no reason to outlive a block, so there is nothing to restore.

## The link exists before the connection does

A `Link` manages a connection; it is not one. It holds the config, the
registry and the current state from the moment the `Camera` is built, which is
why `camera.link.state` is answerable before anything has been opened.

Connecting is atomic. It opens the session, reads the manifest and loads the
registry, or it fails and records why. `UP` with an empty registry is not
representable, because a link you cannot resolve a path through is not a link.

## Versions are accepted, not discovered

A body offers several API versions at once, and the newest is not automatically
the one to speak: a firmware update would silently move every call to a version
nobody has tried. `accepted_version` caps what this client will use, the
highest version at or below it wins, and `offered_beyond_accepted` says what
was left on the table.

## Concurrency is the camera's to arbitrate

Only one device may be connected to a camera at a time. Within that one
connection nothing forbids requests in flight together, and the camera refuses
what it cannot serve, by name: `During shooting or recording`, `Device busy`,
`Mode not supported`, `Already started`.

Which is why refusals are split rather than retried alike. `Device busy` and
`Taken in preparation` clear on their own and are worth waiting out.
`Mode not supported` and `Already started` never will, and backing off three
times before failing only spends the time.

## Layout

| file | what it answers |
|---|---|
| `config.py` | where the camera is, and what this client will accept from it |
| `vocabulary.py` | every value the protocol names, and every shape it arrives in |
| `errors.py` | what a refusal was, and whether waiting would help |
| `endpoints.py` | what the camera offers, and what may be remembered |
| `framing.py` | where one packet ends in a stream of them |
| `link.py` | one camera, reachable or not, and the requests that reach it |
| `status.py` | what the camera says about itself |
| `settings.py` | what we have told it to be |
| `filesystem.py` | the card: how full it is, and what can be taken off it |
| `functions.py` | the camera's own administration |
| `shooting.py` | stills, focus, zoom, flicker |
| `movie.py` | the mode, and the recording inside it |
| `events.py` | what changed, and how to be told |
| `live_view.py` | the preview stream |
| `camera.py` | the one object a caller holds, and what spans several controllers |

## Using it

```python
from portable.ccapi import Camera, CameraConfig, Setting

camera = Camera(CameraConfig(host="192.168.1.2"))

with camera.connection():
    camera.settings.apply({Setting.ISO: "400", Setting.TV: "1/125"})

    with camera.events.watching() as feed:
        camera.shooting.capture(af=False)
        for change in feed:
            for path in change.added:
                camera.files.fetch(path)
```
