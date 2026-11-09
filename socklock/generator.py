"""generate: winning script -> N variants with IDs, saved to SQLite and to out/ files.

Used by both the CLI (`generate`) and the web page (`serve`).
"""
import json
from pathlib import Path

from . import backends, config, ids, library, storage
from . import script as script_mod
from .backends import GenerationError
from .script import ELEMENTS, FIRST_LINES_SCENES

# Stable instructions: identical on every run, placed BEFORE the style library in the system
# prompt. Everything that changes per run (the script, context, N) goes into the user message.
SYSTEM_INSTRUCTIONS = """\
You are a senior direct-response copywriter for SockLock, a US subscription brand that sells \
magnetic socks (5 pairs for $29, then a refill every quarter). Video ads run on Meta \
(Facebook and Instagram Reels) for a US audience.

Your job: take a proven winning video ad script and write variants of selected text elements, \
so motion designers can produce new ad modifications fast. The footage stays the same; only the words change.

Elements:
- hook: the voiceover of scene 1, the first ~3 seconds that must stop the scroll.
- first_lines: the voiceover of scenes 2-3, which keeps the viewer watching after the hook.
- onscreen_text: the short text overlay of each scene (many people watch with sound off).

Rules:
- Follow the style guide strictly: tone, banned words, length limits.
- Learn from the winning scripts: their rhythm, specificity and structure. Do not copy their lines.
- Every line must fit the visual of its scene.
- Never invent claims, prices, discounts or guarantees that are not in the script, the context or the style guide.
- Make the variants clearly different from each other: each one uses its own angle \
(pain point, humor, social proof, curiosity, demo, ...).
- Write in the language of the winning script, unless the context asks for another language.
- Return only the JSON that matches the schema.

Below are the SockLock style guide and past winning scripts."""


def build_system_prompt(library_dir):
    """Stable prefix: instructions + style guide + winners. Cached by the model provider."""
    return SYSTEM_INSTRUCTIONS + "\n\n" + library.build_library_text(library_dir)


def build_user_message(script, elements, n, context):
    """The part that changes on every run."""
    current = script_mod.current_elements(script)
    n_lines = len(current["first_lines"])
    lines = [
        "Winning script to modify (JSON):",
        "<winning_script>",
        json.dumps(script, ensure_ascii=False, indent=2),
        "</winning_script>",
        "",
    ]
    if context:
        lines.append("<context>")
        lines += [f"{key.capitalize()}: {value}" for key, value in context.items()]
        lines += ["</context>", ""]
    lines.append(f"Write {n} variants. Rewrite ONLY these elements: {', '.join(elements)}.")
    if "hook" in elements:
        lines.append(f'- hook: a new voiceover for scene 1. Current: "{current["hook"]}"')
    if "first_lines" in elements:
        lines.append(f"- first_lines: exactly {n_lines} new voiceover lines, for scenes 2-{1 + n_lines} in order.")
    if "onscreen_text" in elements:
        lines.append(f"- onscreen_text: exactly {len(script['scenes'])} short on-screen texts, one per scene, in order.")
    lines.append("For elements NOT listed above return an empty string (hook) or an empty list.")
    lines.append('Name the angle of each variant in "angle" (max 6 words).')
    return "\n".join(lines)


def check_request(script, elements, n):
    if not elements:
        raise ValueError(f"Оберіть хоча б один елемент: {', '.join(ELEMENTS)}")
    unknown = [e for e in elements if e not in ELEMENTS]
    if unknown:
        raise ValueError(f"Невідомі елементи: {', '.join(unknown)}. Можливі: {', '.join(ELEMENTS)}")
    if not 1 <= n <= config.MAX_VARIANTS:
        raise ValueError(f"Кількість варіантів має бути від 1 до {config.MAX_VARIANTS}.")
    if "first_lines" in elements and len(script["scenes"]) < 2:
        raise ValueError("Для first_lines потрібно щонайменше 2 сцени.")


def new_unique_generation_id(db_path):
    while True:
        generation_id = ids.new_generation_id()
        if not storage.generation_exists(db_path, generation_id):
            return generation_id


def generate(script, elements=ELEMENTS, n=config.DEFAULT_VARIANTS, context=None, *,
             backend="cli", model=config.DEFAULT_MODEL, effort=config.DEFAULT_EFFORT,
             library_dir=config.LIBRARY_DIR, db_path=config.DB_PATH, out_dir=config.OUT_DIR,
             run=None, client=None):
    """Main function. Returns the saved generation dict (see storage.save_generation).

    `run` (fake subprocess.run) and `client` (fake anthropic client) are only for tests.
    """
    check_request(script, elements, n)
    elements = [e for e in ELEMENTS if e in elements]  # keep the standard order
    context = {key: value.strip() for key, value in (context or {}).items() if value and value.strip()}

    # 1. Ask the model (or the fake generator) for the new texts.
    if backend == "mock":
        n_lines = len(script_mod.current_elements(script)["first_lines"])
        data, served_model, usage = backends.mock_variants(n, n_lines, len(script["scenes"]), elements)
        model = "mock"
    else:
        system_text = build_system_prompt(library_dir)
        user_text = build_user_message(script, elements, n, context)
        if backend == "cli":
            data, served_model, usage = backends.call_cli(system_text, user_text, model, effort, run=run)
        elif backend == "api":
            data, served_model, usage = backends.call_api(system_text, user_text, model, effort, client=client)
        else:
            raise ValueError(f"Невідомий backend '{backend}'. Можливі: {', '.join(backends.BACKENDS)}")

    raw_variants = data["variants"][:n]
    if not raw_variants:
        raise GenerationError("Модель не повернула жодного варіанта.")

    # 2. Build full variant scripts: copy of the original with only the chosen elements replaced.
    generation_id = new_unique_generation_id(db_path)
    variants = []
    for number, rewrite in enumerate(raw_variants, start=1):
        variants.append({
            "id": ids.variant_id(generation_id, number),
            "n": number,
            "angle": rewrite.get("angle", ""),
            "script": script_mod.apply_rewrite(script, rewrite, elements),
        })

    generation = {
        "id": generation_id,
        "created_at": storage.now(),
        "backend": backend,
        "model": model,
        "served_model": served_model,
        "effort": effort if backend != "mock" else None,
        "elements": elements,
        "context": context,
        "input_script": script,
        "usage": usage,
        "variants": variants,
        "requested": n,
    }

    # 3. Save to SQLite and write the Markdown + JSON files.
    storage.save_generation(db_path, generation)
    generation["files"] = [str(path) for path in write_outputs(generation, out_dir)]
    return generation


def write_outputs(generation, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{generation['id']}.md"
    json_path = out_dir / f"{generation['id']}.json"
    md_path.write_text(to_markdown(generation), encoding="utf-8")
    json_path.write_text(json.dumps(generation, ensure_ascii=False, indent=2), encoding="utf-8")
    return md_path, json_path


def to_markdown(generation):
    g = generation
    lines = [f"# {g['id']}: {len(g['variants'])} variants of \"{g['input_script']['title']}\"", ""]
    if g["backend"] == "mock":
        lines += ["> MOCK: офлайн-заглушка для тестів і демо, НЕ текст від Claude.", ""]
    lines += [
        f"- Model: {g['model']} (backend: {g['backend']})",
        f"- Elements: {', '.join(g['elements'])}",
        f"- Created: {g['created_at']}",
        "- Paste the variant ID into the Meta ad name.",
        "",
    ]
    for variant in g["variants"]:
        lines += [f"## {variant['id']}", "", f"Angle: {variant['angle']}", ""]
        lines.append(script_mod.scenes_to_markdown(variant["script"]["scenes"], level=3))
    return "\n".join(lines)


def changed_texts(generation, variant):
    """Only the rewritten texts of one variant, for compact printing (CLI and web)."""
    scenes = variant["script"]["scenes"]
    result = {}
    if "hook" in generation["elements"]:
        result["hook"] = scenes[0]["voiceover"]
    if "first_lines" in generation["elements"]:
        result["first_lines"] = [s["voiceover"] for s in scenes[1:1 + FIRST_LINES_SCENES]]
    if "onscreen_text" in generation["elements"]:
        result["onscreen_text"] = [s["onscreen_text"] for s in scenes]
    return result
