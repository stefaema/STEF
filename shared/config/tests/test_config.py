import pytest

from shared import config, paths

PACKAGE = "shared.config.tests.fixture"


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.ENV_HOME, str(tmp_path / "home"))
    return tmp_path / "home"


def written(file, text):
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text)
    return file


# ── The shipped file and yours ───────────────────────────────────────────────


def test_what_a_package_ships_is_read_when_nothing_overrides_it(home):
    assert config.get(PACKAGE, "drivers", "shipped.toml") == {
        "irun": 8,
        "chopconf": {"toff": 3, "mres": 0},
    }


def test_your_copy_wins_key_by_key_and_leaves_the_rest_shipped(home):
    written(
        home / "config/drivers/shipped.toml",
        "irun = 16\n\n[chopconf]\ntoff = 5\n",
    )

    assert config.get(PACKAGE, "drivers", "shipped.toml") == {
        "irun": 16,
        "chopconf": {"toff": 5, "mres": 0},
    }


def test_a_file_only_you_have_is_read_with_nothing_under_it(home):
    written(home / "config/drivers/mine.toml", "irun = 4\n")

    assert config.get(PACKAGE, "drivers", "mine.toml") == {"irun": 4}


def test_neither_root_holding_the_file_names_both(home):
    with pytest.raises(config.ConfigError, match="neither .* nor .* is there"):
        config.get(PACKAGE, "drivers", "absent.toml")


def test_a_file_that_is_not_toml_says_so_and_names_itself(home):
    written(home / "config/drivers/broken.toml", "irun = = 8\n")

    with pytest.raises(config.ConfigError, match="not readable TOML"):
        config.get(PACKAGE, "drivers", "broken.toml")


# ── What there is to choose from ─────────────────────────────────────────────


def test_the_choices_are_the_shipped_ones_and_yours_without_repeating_either(home):
    written(home / "config/drivers/shipped.toml", "irun = 16\n")
    written(home / "config/drivers/mine.toml", "irun = 4\n")
    written(home / "config/drivers/notes.txt", "not a profile\n")

    assert config.available(PACKAGE, "drivers") == ("mine", "shipped")


def test_a_directory_neither_root_has_offers_nothing(home):
    assert config.available(PACKAGE, "absent") == ()
