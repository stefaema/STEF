from pathlib import Path

import pytest

from shared import paths

XDG = ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME")


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    monkeypatch.delenv(paths.ENV_HOME, raising=False)
    for variable in XDG:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return tmp_path


# ── Where the roots come from ────────────────────────────────────────────────


def test_a_named_home_holds_every_root_under_one_directory(clean_env, monkeypatch):
    monkeypatch.setenv(paths.ENV_HOME, str(clean_env / "local"))

    assert paths.config_dir() == clean_env / "local/config"
    assert paths.state_dir() == clean_env / "local/state"
    assert paths.firmware_dir() == clean_env / "local/firmware"


def test_without_a_home_each_root_follows_its_own_xdg_variable(clean_env, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(clean_env / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(clean_env / "st"))
    monkeypatch.setenv("XDG_DATA_HOME", str(clean_env / "dt"))

    assert paths.config_dir() == clean_env / "cfg" / paths.APP
    assert paths.state_dir() == clean_env / "st" / paths.APP
    assert paths.firmware_dir() == clean_env / "dt" / paths.APP / "firmware"


def test_without_xdg_either_the_defaults_are_the_spec_s(clean_env):
    house = Path(clean_env / "home")

    assert paths.config_dir() == house / ".config" / paths.APP
    assert paths.state_dir() == house / ".local/state" / paths.APP
    assert paths.firmware_dir() == house / ".local/share" / paths.APP / "firmware"


def test_a_relative_root_is_not_a_root(clean_env, monkeypatch):
    monkeypatch.setenv(paths.ENV_HOME, "local")
    assert paths.home() is None
    assert paths.config_dir() == Path(clean_env / "home") / ".config" / paths.APP

    monkeypatch.setenv("XDG_CONFIG_HOME", "cfg")
    assert paths.config_dir() == Path(clean_env / "home") / ".config" / paths.APP


def test_an_empty_variable_is_an_unset_one(clean_env, monkeypatch):
    monkeypatch.setenv(paths.ENV_HOME, "")
    assert paths.home() is None


def test_a_home_wins_over_xdg(clean_env, monkeypatch):
    monkeypatch.setenv(paths.ENV_HOME, str(clean_env / "local"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(clean_env / "cfg"))

    assert paths.config_dir() == clean_env / "local/config"


# ── What a module ships ──────────────────────────────────────────────────────


def test_a_package_carries_its_builtin_beside_its_code():
    assert paths.builtin_dir("shared") == Path(__file__).parent.parent / "builtin"
    assert paths.builtin_dir("transport").is_dir()


def test_the_builtin_tree_is_reachable_by_name():
    capstan = paths.builtin("transport", "devices", "capstan.toml")
    assert capstan.is_file()
    assert capstan.parent.name == "devices"


def test_a_package_that_is_not_there_says_so():
    with pytest.raises(paths.PathsError):
        paths.builtin_dir("no_such_module_of_ours")


# ── The two places one file can live ─────────────────────────────────────────


def test_a_file_has_one_name_under_two_roots(clean_env, monkeypatch):
    monkeypatch.setenv(paths.ENV_HOME, str(clean_env / "local"))

    shipped, mine = paths.layered("transport", "devices", "capstan.toml")
    assert shipped == paths.builtin_dir("transport") / "devices/capstan.toml"
    assert mine == clean_env / "local/config/devices/capstan.toml"


def test_the_shipped_file_is_offered_before_yours(clean_env, monkeypatch):
    monkeypatch.setenv(paths.ENV_HOME, str(clean_env / "local"))
    assert paths.readable("transport", "devices", "capstan.toml") == [
        paths.builtin("transport", "devices", "capstan.toml")
    ]

    mine = paths.ensure_parent(clean_env / "local/config/devices/capstan.toml")
    mine.write_text("")

    found = paths.readable("transport", "devices", "capstan.toml")
    assert found == [paths.builtin("transport", "devices", "capstan.toml"), mine]


def test_a_file_neither_root_holds_is_not_readable(clean_env, monkeypatch):
    monkeypatch.setenv(paths.ENV_HOME, str(clean_env / "local"))
    assert paths.readable("transport", "devices", "flywheel.toml") == []


def test_a_directory_is_not_a_layered_file():
    with pytest.raises(paths.PathsError):
        paths.layered("transport")


# ── Making room to write ─────────────────────────────────────────────────────


def test_ensure_makes_the_whole_chain(clean_env):
    made = paths.ensure(clean_env / "one/two/three")
    assert made.is_dir()
    assert paths.ensure(made) == made


def test_ensure_parent_leaves_the_file_to_the_caller(clean_env):
    target = paths.ensure_parent(clean_env / "logs/today/session.json")
    assert target.parent.is_dir()
    assert not target.exists()
