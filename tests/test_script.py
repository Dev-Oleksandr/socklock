import json

import pytest

from socklock import script as script_mod

MARKDOWN = """# Laundry day

Some note before the first scene is ignored.

## Scene 1
Visual: Dryer full of socks
VO: Every laundry day I lose a sock.
On-screen: WHERE DO THEY GO

## Scene 2
Visual: Socks snap together
**VO:** So I tried magnetic socks.
continued on the next line.
OST: MAGNETS

## Scene 3
VO: They come out as a pair.

## Scene 4
VO: Five pairs for $29.
On-screen: 5 PAIRS FOR $29
"""


def test_parse_markdown():
    script = script_mod.parse_script_text(MARKDOWN)
    assert script["title"] == "Laundry day"
    assert len(script["scenes"]) == 4
    assert script["scenes"][0] == {"visual": "Dryer full of socks",
                                   "voiceover": "Every laundry day I lose a sock.",
                                   "onscreen_text": "WHERE DO THEY GO"}
    # bold key, continuation line and the "OST" alias
    assert script["scenes"][1]["voiceover"] == "So I tried magnetic socks. continued on the next line."
    assert script["scenes"][1]["onscreen_text"] == "MAGNETS"
    assert script["scenes"][2]["onscreen_text"] == ""


def test_parse_json_with_aliases():
    text = json.dumps({"title": "T", "scenes": [
        {"visual": "v1", "line": "hello", "on_screen_text": "HI"},
        {"Voiceover": "second", "text": "TWO"},
    ]})
    script = script_mod.parse_script_text(text)
    assert script["scenes"][0] == {"visual": "v1", "voiceover": "hello", "onscreen_text": "HI"}
    assert script["scenes"][1]["voiceover"] == "second"
    assert script["scenes"][1]["onscreen_text"] == "TWO"


def test_invalid_scripts():
    with pytest.raises(ValueError):
        script_mod.parse_script_text("# Only a title")
    with pytest.raises(ValueError):
        script_mod.parse_script_text("## Scene 1\nOn-screen: no voiceover")
    with pytest.raises(ValueError):
        script_mod.parse_script_text("{not json")


def test_current_elements():
    current = script_mod.current_elements(script_mod.parse_script_text(MARKDOWN))
    assert current["hook"] == "Every laundry day I lose a sock."
    assert current["first_lines"] == ["So I tried magnetic socks. continued on the next line.",
                                      "They come out as a pair."]
    assert len(current["onscreen_text"]) == 4


def test_apply_rewrite_changes_only_chosen_elements():
    original = script_mod.parse_script_text(MARKDOWN)
    rewrite = {"hook": "NEW HOOK", "first_lines": ["NEW 2", "NEW 3"], "onscreen_text": ["A", "B", "C", "D"]}
    new = script_mod.apply_rewrite(original, rewrite, ["hook"])
    assert new["scenes"][0]["voiceover"] == "NEW HOOK"
    assert new["scenes"][1]["voiceover"] == original["scenes"][1]["voiceover"]
    assert [s["onscreen_text"] for s in new["scenes"]] == [s["onscreen_text"] for s in original["scenes"]]
    assert original["scenes"][0]["voiceover"] == "Every laundry day I lose a sock."  # original untouched

    new = script_mod.apply_rewrite(original, rewrite, ["first_lines", "onscreen_text"])
    assert new["scenes"][0]["voiceover"] == original["scenes"][0]["voiceover"]
    assert [s["voiceover"] for s in new["scenes"][1:3]] == ["NEW 2", "NEW 3"]
    assert new["scenes"][3]["voiceover"] == "Five pairs for $29."  # scene 4 VO is never touched
    assert [s["onscreen_text"] for s in new["scenes"]] == ["A", "B", "C", "D"]
    assert [s["visual"] for s in new["scenes"]] == [s["visual"] for s in original["scenes"]]


def test_apply_rewrite_keeps_original_when_model_returns_too_few_lines():
    original = script_mod.parse_script_text(MARKDOWN)
    new = script_mod.apply_rewrite(original, {"onscreen_text": ["ONLY ONE"]}, ["onscreen_text"])
    assert new["scenes"][0]["onscreen_text"] == "ONLY ONE"
    assert new["scenes"][3]["onscreen_text"] == "5 PAIRS FOR $29"


def test_markdown_round_trip():
    original = script_mod.parse_script_text(MARKDOWN)
    assert script_mod.parse_script_text(script_mod.to_markdown(original)) == original


FRONT_MATTER_DOC = """---
context: Продукт: магнітні шкарпетки SockLock. Пиши українською.
elements: hook, onscreen_text, subject_line
variants: 7
model: claude-opus-5-5
colour: green
---
# Title
## Scene 1
VO: Hello
"""


def test_front_matter_is_split_and_cleaned():
    script, settings = script_mod.parse_document(FRONT_MATTER_DOC)
    assert script["title"] == "Title" and script["scenes"][0]["voiceover"] == "Hello"
    assert settings == {
        "context": "Продукт: магнітні шкарпетки SockLock. Пиши українською.",  # only the first ':' splits
        "elements": ["hook", "onscreen_text"],                              # unknown element dropped
        "variants": 7,
        "model": "claude-opus-5-5",
    }                                                                       # unknown key ignored


def test_no_or_broken_front_matter():
    assert script_mod.parse_document(MARKDOWN)[1] == {}
    meta, body = script_mod.split_front_matter("---\nvariants: 3\n# no closing line\n## Scene 1\nVO: x")
    assert meta == {} and body.startswith("---")
    _, settings = script_mod.parse_document("---\nvariants: many\nelements: nothing\n---\n## Scene 1\nVO: x")
    assert settings == {}  # invalid values are dropped, defaults stay


def test_json_settings():
    text = json.dumps({"title": "T", "context": "Пиши українською.", "elements": ["first_lines"],
                       "variants": "4", "scenes": [{"vo": "a"}, {"vo": "b"}]})
    script, settings = script_mod.parse_document(text)
    assert len(script["scenes"]) == 2
    assert settings == {"context": "Пиши українською.", "elements": ["first_lines"], "variants": 4}


def test_parse_script_text_ignores_front_matter():
    assert script_mod.parse_script_text(FRONT_MATTER_DOC)["scenes"] == [
        {"visual": "", "voiceover": "Hello", "onscreen_text": ""}]
