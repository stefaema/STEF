"""What each change the model publishes redraws on the screen, and the connections it goes to.

A change is rendered once, on the thread that published it, into the text of one
server-sent event. Every connected browser gets that same text through its own
asyncio queue, so no thread is held per connection.

Fragments that read the same for every viewer travel out of band: HTMX swaps each
one in by its id. The LINK channel also sends `link_state` when the link itself
changed. Each board listens for that, for its own subsystem, and fetches itself
again, since what it shows depends on which tool that viewer has open.
"""

import asyncio
import json
import threading
from typing import Any

from fastapi.templating import Jinja2Templates

from gui.src import view
from gui.src.messages import Change, Channel, LogLine
from gui.src.model import GuiModel
from shared.diagnostics import Needs

# How many rendered events one browser may fall behind by before it misses some.
CONNECTION_DEPTH = 512


def sse_event(name: str, body: str) -> str:
    """Return body as one server-sent event called name, one data line per line."""
    lines = body.splitlines() or [""]
    return f"event: {name}\n" + "".join(f"data: {line}\n" for line in lines) + "\n"


class ScreenBindings:
    def __init__(self, model: GuiModel, templates: Jinja2Templates) -> None:
        """Render model's changes with templates, for every browser that connects."""
        self.model = model
        self.templates = templates
        self._connections: list[
            tuple[asyncio.AbstractEventLoop, asyncio.Queue[str]]
        ] = []
        self._lock = threading.Lock()

    def start(self) -> None:
        self.model.subscribe(self.publish)

    def close(self) -> None:
        self.model.unsubscribe(self.publish)

    # ── Connections ──────────────────────────────────────────────────────────

    def connect(self) -> asyncio.Queue[str]:
        """Return the queue one browser's event stream reads, starting with the log backlog."""
        events: asyncio.Queue[str] = asyncio.Queue(CONNECTION_DEPTH)
        for log_line in self.model.log_backlog():
            events.put_nowait(self.log_event(log_line))
        with self._lock:
            self._connections.append((asyncio.get_running_loop(), events))
        return events

    def disconnect(self, events: asyncio.Queue[str]) -> None:
        with self._lock:
            self._connections = [
                one for one in self._connections if one[1] is not events
            ]

    def publish(self, change: Change) -> None:
        """Render change once and hand the same text to every connected browser."""
        with self._lock:
            connections = list(self._connections)
        if not connections:
            return
        rendered = self.render(change)
        if not rendered:
            return
        for loop, events in connections:
            loop.call_soon_threadsafe(_offer, events, rendered)

    # ── What each channel redraws ────────────────────────────────────────────

    def render(self, change: Change) -> str:
        match change.channel:
            case Channel.LOG:
                return self.log_event(change.log_line) if change.log_line else ""
            case Channel.LINK:
                return self.link_events(change.subsystem_id or "")
            case Channel.TEST_PROGRESS:
                return self.test_progress_event(
                    change.subsystem_id or "", change.test_key or "", change.test_ended
                )
            case Channel.FOCUS:
                return self.focus_event()

    def log_event(self, log_line: LogLine) -> str:
        return sse_event("log", self._render("log/record.html", {"log_line": log_line}))

    def link_events(self, subsystem_id: str) -> str:
        """Return the board's viewer-independent fragments, then link_state if the link moved."""
        template_context = view.tests_tool_context(self.model, subsystem_id)
        template_context["oob"] = True
        fragments = [
            self._render("diagnostics/subsystem_tab_marks.html", template_context),
            self._render("diagnostics/implementation.html", template_context),
            self._render("diagnostics/stop_alarm.html", template_context),
        ]
        subsystem_view = template_context["subsystem_view"]
        for test in subsystem_view.tests:
            if test.needs is Needs.DOWN and template_context["link_is_up"]:
                continue
            fragments.append(
                self._render(
                    "diagnostics/tests/head.html",
                    {
                        **template_context,
                        "test": test,
                        "test_uid": view.slug(f"{subsystem_id}.{test.key}"),
                    },
                )
            )
        link = subsystem_view.link
        link_state = link.state.value if link is not None else "down"
        events = sse_event("link", "".join(fragments))
        events += sse_event(
            "link_state", json.dumps({"subsystem": subsystem_id, "state": link_state})
        )
        return events

    def test_progress_event(self, subsystem_id: str, test_key: str, ended: bool) -> str:
        template_context = view.test_card_context(
            self.model, subsystem_id, test_key, oob=True
        )
        body = self._render("diagnostics/tests/head.html", template_context)
        body += self._render("diagnostics/tests/steps.html", template_context)
        if ended:
            body += self._group_mark(subsystem_id, template_context["test"].group)
        return sse_event("test_progress", body)

    def focus_event(self) -> str:
        _, focus_holder = self.model.focus
        return sse_event(
            "focus",
            self._render(
                "chrome/focus.html", {"focus_holder": focus_holder, "oob": True}
            ),
        )

    def _group_mark(self, subsystem_id: str, group: str) -> str:
        grouped = [
            one
            for one in self.model.subsystem_view(subsystem_id).tests
            if one.group == group and one.needs is not Needs.DOWN
        ]
        if not grouped:
            return ""
        return self._render(
            "diagnostics/tests/mark.html",
            {"items": grouped, "mark_id": view.slug(f"mark-{subsystem_id}-{group}")},
        )

    def _render(self, template: str, template_context: dict[str, Any]) -> str:
        return self.templates.get_template(template).render(**template_context)


def _offer(events: asyncio.Queue[str], rendered: str) -> None:
    """Put rendered on one browser's queue, dropping it for a browser that fell too far behind."""
    try:
        events.put_nowait(rendered)
    except asyncio.QueueFull:
        pass


__all__ = ["CONNECTION_DEPTH", "ScreenBindings", "sse_event"]
