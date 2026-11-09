"""Winning scripts: read Markdown or JSON, write Markdown, swap rewritten elements in.

A script is a plain dict:
    {"title": "...",
     "scenes": [{"visual": "...", "voiceover": "...", "onscreen_text": "..."}, ...]}

The three elements a designer can vary:
    hook          = voiceover of scene 1 (the first ~3 seconds)
    first_lines   = voiceover of scenes 2-3 (the lines right after the hook)
    onscreen_text = on-screen text of every scene
Everything else (visuals, later voiceover) is never changed.
"""
import copy
import json
import re
from pathlib import Path

ELEMENTS = ("hook", "first_lines", "onscreen_text")
SETTING_KEYS = ("context", "elements", "variants", "model")  # allowed in front matter / JSON
FIRST_LINES_SCENES = 2  # how many scenes after the hook count as "first lines"
FIELDS = ("visual", "voiceover", "onscreen_text")

# Accepted spellings of a field name (lowercase) -> our field name.
FIELD_ALIASES = {
    "visual": "visual", "video": "visual", "shot": "visual",
    "vo": "voiceover", "voiceover": "voiceover", "voice-over": "voiceover",
    "voice over": "voiceover", "line": "voiceover",
    "on-screen": "onscreen_text", "on-screen text": "onscreen_text",
    "onscreen": "onscreen_text", "onscreen text": "onscreen_text",
    "onscreen_text": "onscreen_text", "on_screen_text": "onscreen_text",
    "ost": "onscreen_text", "text": "onscreen_text", "super": "onscreen_text",
}

# Labels used when we write a script back to Markdown.
MARKDOWN_LABELS = (("visual", "Visual"), ("voiceover", "VO"), ("onscreen_text", "On-screen"))


def empty_scene():
    return {"visual": "", "voiceover": "", "onscreen_text": ""}


def load_script(path):
    """Read a .md / .txt / .json script file (settings in it are ignored)."""
    return load_document(path)[0]


def load_document(path):
    """Read a script file. Returns (script, settings) - settings come from the front matter / JSON."""
    path = Path(path)
    return parse_document(path.read_text(encoding="utf-8"), fallback_title=path.stem)


def parse_script_text(text, fallback_title="Untitled script"):
    return parse_document(text, fallback_title)[0]


def parse_document(text, fallback_title="Untitled script"):
    """Text that starts with '{' is JSON, anything else is Markdown with optional front matter."""
    text = text.lstrip("﻿")
    if text.lstrip().startswith("{"):
        script = parse_json(text)
        raw_settings = {key: value for key, value in json.loads(text).items() if key in SETTING_KEYS}
    else:
        raw_settings, body = split_front_matter(text)
        script = parse_markdown(body)
    if not script["title"]:
        script["title"] = fallback_title
    validate(script)
    return script, clean_settings(raw_settings)


def split_front_matter(text):
    """Optional block at the very top of a Markdown file:
        ---
        context: Product: ... Пиши українською.
        elements: hook, first_lines
        variants: 10
        model: claude-sonnet-5-5
        ---
    Returns ({key: value}, rest of the text). Unknown keys are ignored.
    No closing '---' means there is no front matter.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for end in range(1, len(lines)):
        if lines[end].strip() == "---":
            settings = {}
            for line in lines[1:end]:
                key, separator, value = line.partition(":")  # only the FIRST ':' splits
                key = key.strip().lower()
                if separator and key in SETTING_KEYS:
                    settings[key] = value.strip()
            return settings, "\n".join(lines[end + 1:])
    return {}, text


def clean_settings(raw):
    """Turn raw values (strings from front matter, or JSON values) into checked settings.
    Invalid values are dropped, so the defaults stay."""
    settings = {}
    if isinstance(raw.get("context"), str) and raw["context"].strip():
        settings["context"] = raw["context"].strip()
    elements = raw.get("elements")
    if isinstance(elements, str):
        elements = re.split(r"[,\s]+", elements)
    if isinstance(elements, list):
        chosen = [e for e in ELEMENTS if e in [str(item).strip() for item in elements]]
        if chosen:
            settings["elements"] = chosen
    try:
        variants = int(raw.get("variants"))
        if variants >= 1:
            settings["variants"] = variants
    except (TypeError, ValueError):
        pass
    if isinstance(raw.get("model"), str) and raw["model"].strip():
        settings["model"] = raw["model"].strip()
    return settings


def parse_json(text):
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"Не вдалося прочитати JSON: {error}") from error
    scenes = []
    for raw_scene in data.get("scenes", []):
        scene = empty_scene()
        for key, value in raw_scene.items():
            field = FIELD_ALIASES.get(key.strip().lower())
            if field:
                scene[field] = str(value).strip()
        scenes.append(scene)
    return {"title": str(data.get("title", "")).strip(), "scenes": scenes}


def parse_markdown(text):
    """Format:
        # Title
        ## Scene 1
        Visual: ...
        VO: ...
        On-screen: ...
    Any '##' heading starts a new scene. A line without a known 'Key:' continues the previous field.
    """
    title = ""
    scenes = []
    last_field = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("##"):
            scenes.append(empty_scene())
            last_field = None
        elif stripped.startswith("# "):
            title = stripped[2:].strip()
        elif stripped and scenes:
            key, separator, value = stripped.partition(":")
            field = FIELD_ALIASES.get(key.strip(" -*_").lower()) if separator else None
            if field:
                scenes[-1][field] = value.strip(" *_")
                last_field = field
            elif last_field:
                scenes[-1][last_field] = (scenes[-1][last_field] + " " + stripped).strip()
    return {"title": title, "scenes": scenes}


def validate(script):
    if not script["scenes"]:
        raise ValueError("У сценарії немає сцен. Кожна сцена починається з '## Scene N' (або ключ 'scenes' у JSON).")
    if not script["scenes"][0]["voiceover"]:
        raise ValueError("У сцени 1 немає озвучки (VO) — без неї неможливо переписати хук.")


def current_elements(script):
    """The texts that the three elements currently have."""
    scenes = script["scenes"]
    return {
        "hook": scenes[0]["voiceover"],
        "first_lines": [scene["voiceover"] for scene in scenes[1:1 + FIRST_LINES_SCENES]],
        "onscreen_text": [scene["onscreen_text"] for scene in scenes],
    }


def apply_rewrite(script, rewrite, elements):
    """Return a COPY of the script where only the chosen elements are replaced.

    `rewrite` is one variant from the model: {"hook": str, "first_lines": [...], "onscreen_text": [...]}.
    If the model returned fewer lines than needed, the original text stays for the missing ones.
    """
    new_script = copy.deepcopy(script)
    scenes = new_script["scenes"]
    if "hook" in elements and rewrite.get("hook"):
        scenes[0]["voiceover"] = rewrite["hook"].strip()
    if "first_lines" in elements:
        for scene, line in zip(scenes[1:1 + FIRST_LINES_SCENES], rewrite.get("first_lines", [])):
            if line.strip():
                scene["voiceover"] = line.strip()
    if "onscreen_text" in elements:
        for scene, text in zip(scenes, rewrite.get("onscreen_text", [])):
            if text.strip():
                scene["onscreen_text"] = text.strip()
    return new_script


def scenes_to_markdown(scenes, level=2):
    hashes = "#" * level
    lines = []
    for number, scene in enumerate(scenes, start=1):
        lines.append(f"{hashes} Scene {number}")
        for field, label in MARKDOWN_LABELS:
            if scene[field]:
                lines.append(f"{label}: {scene[field]}")
        lines.append("")
    return "\n".join(lines)


def to_markdown(script):
    """The same format parse_markdown() reads, so the output can be fed back in."""
    return f"# {script['title']}\n\n" + scenes_to_markdown(script["scenes"])
