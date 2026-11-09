"""Style library: library/style_guide.md + library/winners/*.md.

Its text goes into the system prompt as a STABLE prefix (few-shot examples).
Stable = byte-identical between runs, so the model provider can cache it.
"""
import shutil
from pathlib import Path

from . import script as script_mod


def style_guide_path(library_dir):
    return Path(library_dir) / "style_guide.md"


def winners_dir(library_dir):
    return Path(library_dir) / "winners"


def load_style_guide(library_dir):
    path = style_guide_path(library_dir)
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def load_winners(library_dir):
    """[(file name, text), ...] sorted by name, so the prompt is the same on every run."""
    folder = winners_dir(library_dir)
    if not folder.exists():
        return []
    files = sorted(path for path in folder.iterdir() if path.suffix in (".md", ".json"))
    return [(path.name, path.read_text(encoding="utf-8").strip()) for path in files]


def build_library_text(library_dir):
    """Style guide + winners as one text. XML-like tags help the model tell the parts apart."""
    parts = ["<style_guide>", load_style_guide(library_dir) or "(no style guide yet)", "</style_guide>",
             "", "<winning_scripts>"]
    for name, text in load_winners(library_dir):
        parts += [f'<script file="{name}">', text, "</script>"]
    parts.append("</winning_scripts>")
    return "\n".join(parts)


def add_winner_file(library_dir, file_path):
    """`library add <file>`: check that the file is a valid script, then copy it into winners/."""
    source = Path(file_path)
    script_mod.load_script(source)  # raises ValueError if the file is not a valid script
    folder = winners_dir(library_dir)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / source.name
    shutil.copyfile(source, target)
    return target


def save_winner_script(library_dir, variant_id, script, result_note=""):
    """Feedback loop: write a winning variant into winners/<variant_id>.md.

    Returns the new path, or None if this winner is already in the library.
    The 'Result:' line sits before the first scene, so the script parser ignores it,
    but the model sees it in the prompt.
    """
    folder = winners_dir(library_dir)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{variant_id}.md"
    if target.exists():
        return None
    text = f"# {script['title']} ({variant_id})\n\n"
    if result_note:
        text += f"Result: {result_note}\n\n"
    text += script_mod.scenes_to_markdown(script["scenes"])
    target.write_text(text, encoding="utf-8")
    return target
