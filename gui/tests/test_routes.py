"""The operator's routes, against the real app with the demo subsystem served."""

import pytest
from fastapi.testclient import TestClient

from demo.bench import link as demo_link
from shared import paths


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """Return a client against the real app, with demo served and a state directory of its own."""
    with pytest.MonkeyPatch.context() as patched:
        patched.setenv(paths.ENV_HOME, str(tmp_path_factory.mktemp("home")))
        patched.setenv("STEF_DEMO", "1")
        patched.setattr(demo_link, "PACE_S", 0.0)
        from gui.src import app as app_module
        from gui.src.model import GuiModel

        patched.setattr(app_module, "model", GuiModel())
        patched.setattr(app_module.bindings, "model", app_module.model)
        with TestClient(app_module.app) as started:
            yield started


def test_the_screen_renders_from_what_the_model_holds(client):
    page = client.get("/diagnostics/demo")
    assert page.status_code == 200
    assert "STEF" in page.text
    assert 'sse-connect="/diagnostics/events"' in page.text


def test_a_tool_that_needs_the_link_sends_you_back_to_link_while_it_is_down(client):
    page = client.get("/diagnostics/demo/tests", follow_redirects=False)
    assert page.status_code == 307
    assert page.headers["location"] == "/diagnostics/demo"


def test_a_subsystem_that_is_not_served_is_a_404(client):
    assert client.get("/diagnostics/nothing").status_code == 404


def test_connecting_then_running_returns_the_steps(client):
    connected = client.post("/diagnostics/demo/link/connect", data={"board": "healthy"})
    assert connected.status_code == 200
    assert "Disconnect" in connected.text

    ran = client.post("/diagnostics/demo/tests/outcomes.Passes/run")
    assert ran.status_code == 200
    assert 'id="steps-demo-outcomes-Passes"' in ran.text

    client.post("/diagnostics/demo/link/disconnect")


def test_answering_when_nothing_is_asked_is_refused(client):
    refused = client.post("/diagnostics/demo/tests/asking.Asks/answer", data={})
    assert refused.status_code == 409


def test_a_stop_with_the_link_down_shows_the_alarm(client):
    stopped = client.post("/diagnostics/demo/stop")
    assert "not sent" in stopped.text
    assert "A stop did not reach the hardware" in stopped.text

    acknowledged = client.post("/diagnostics/demo/alarm/acknowledge")
    assert "A stop did not reach the hardware" not in acknowledged.text


def test_every_channel_renders_into_server_sent_events(client):
    from gui.src import app as app_module
    from gui.src.messages import Change, Channel

    client.post("/diagnostics/demo/link/connect", data={"board": "healthy"})
    client.post("/diagnostics/demo/tests/outcomes.Passes/run")
    screen = app_module.bindings

    link = screen.render(Change(Channel.LINK, subsystem_id="demo"))
    assert link.startswith("event: link\n")
    assert 'id="implementation-demo"' in link
    assert "event: link_state\n" in link

    progress = screen.render(
        Change(Channel.TEST_PROGRESS, "demo", "outcomes.Passes", test_ended=True)
    )
    assert progress.startswith("event: test_progress\n")
    assert 'id="head-demo-outcomes-Passes"' in progress
    assert 'hx-swap-oob="true"' in progress

    assert screen.render(Change(Channel.FOCUS)).startswith("event: focus\n")

    logged = screen.log_event(app_module.model.log_backlog()[-1])
    assert logged.startswith("event: log\n")
    client.post("/diagnostics/demo/link/disconnect")
