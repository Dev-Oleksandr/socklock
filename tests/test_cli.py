"""generate: explicit CLI flags win over the file's front matter, which wins over defaults."""
from pathlib import Path

from socklock import cli, config
from socklock import script as script_mod

EXAMPLES = Path(__file__).parent.parent / "socklock" / "demo_data" / "examples"
FILE_SETTINGS = {"context": "Пиши українською.", "elements": ["hook"], "variants": 4, "model": "claude-opus-5-5"}


def options(*flags, settings=None):
    args = cli.build_parser().parse_args(["generate", "file.md", *flags])
    return cli.generate_options(args, settings or {})


def test_defaults_without_flags_or_front_matter():
    result = options()
    assert result["elements"] == ["hook", "first_lines", "onscreen_text"]
    assert result["n"] == config.DEFAULT_VARIANTS
    assert result["model"] == config.DEFAULT_MODEL
    assert result["context"]["context"] == ""


def test_front_matter_fills_options():
    result = options(settings=FILE_SETTINGS)
    assert result["elements"] == ["hook"] and result["n"] == 4 and result["model"] == "claude-opus-5-5"
    assert result["context"]["context"] == "Пиши українською."


def test_flags_win_over_front_matter():
    result = options("-n", "2", "-e", "onscreen_text", "--model", "claude-sonnet-5-5",
                     "--context", "Write in English.", "--product", "socks", settings=FILE_SETTINGS)
    assert result["elements"] == ["onscreen_text"] and result["n"] == 2
    assert result["model"] == "claude-sonnet-5-5"
    assert result["context"] == {"context": "Write in English.", "product": "socks", "audience": "", "angle": ""}


def test_example_files():
    files = sorted(EXAMPLES.glob("*.md"))
    assert len(files) == 6
    for path in files:
        script, settings = script_mod.load_document(path)
        assert len(script["scenes"]) >= 4
        assert set(settings) == {"context", "elements", "variants", "model"}
        assert ("Пиши українською." in settings["context"]) == path.name.startswith("uk_")
