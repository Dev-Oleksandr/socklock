import pytest

from socklock import generator, library


def test_library_text_is_stable_and_complete(tmp_path):
    (tmp_path / "winners").mkdir()
    (tmp_path / "style_guide.md").write_text("Tone: friendly.", encoding="utf-8")
    (tmp_path / "winners" / "b.md").write_text("# B\n## Scene 1\nVO: second", encoding="utf-8")
    (tmp_path / "winners" / "a.md").write_text("# A\n## Scene 1\nVO: first", encoding="utf-8")
    text = library.build_library_text(tmp_path)
    assert "Tone: friendly." in text
    assert text.index('file="a.md"') < text.index('file="b.md"')  # sorted -> same bytes every run
    assert library.build_library_text(tmp_path) == text
    assert generator.build_system_prompt(tmp_path).startswith(generator.SYSTEM_INSTRUCTIONS)


def test_add_winner_file(tmp_path):
    source = tmp_path / "new_winner.md"
    source.write_text("# New\n## Scene 1\nVO: A great hook", encoding="utf-8")
    target = library.add_winner_file(tmp_path / "library", source)
    assert target.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")

    broken = tmp_path / "broken.md"
    broken.write_text("just some text", encoding="utf-8")
    with pytest.raises(ValueError):
        library.add_winner_file(tmp_path / "library", broken)


def test_save_winner_script_once(tmp_path):
    script = {"title": "T", "scenes": [{"visual": "", "voiceover": "Hook", "onscreen_text": "HI"}]}
    path = library.save_winner_script(tmp_path, "SLM-20261109-AAAA-v1", script, "CTR 2%, ROMI 150%")
    text = path.read_text(encoding="utf-8")
    assert "Result: CTR 2%, ROMI 150%" in text and "VO: Hook" in text
    assert library.save_winner_script(tmp_path, "SLM-20261109-AAAA-v1", script) is None
