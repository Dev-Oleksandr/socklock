"""serve: a local web page for designers. Python stdlib only (http.server), no frameworks.

GET  /          -> the form
POST /generate  -> runs generator.generate() (the same function as the CLI) and shows the variants

The page is one HTML document: CSS and JS are plain strings below, the HTML around them is built
with f-strings. Every text that comes from the user or the model goes through html.escape().
"""
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from . import config, generator
from . import script as script_mod
from .backends import GenerationError
from .script import FIRST_LINES_SCENES

ELEMENT_LABELS = {"hook": "Хук", "first_lines": "Перші фрази", "onscreen_text": "Текст на екрані"}
MODEL_OPTIONS = [("claude-sonnet-5-5", "Sonnet 5.5"), ("claude-opus-5-5", "Opus 5.5")]
EXAMPLES_DIR = Path(__file__).parent / "demo_data" / "examples"
FONT_URL = "https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700&display=swap"
COPY_ICON = ('<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
             'stroke-width="2" aria-hidden="true"><rect x="9" y="9" width="12" height="12" rx="2"/>'
             '<path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>')


def load_examples():
    """Built-in example files (with front matter). Embedded in the page as JSON."""
    examples = []
    for path in sorted(EXAMPLES_DIR.glob("*.md")):
        script = script_mod.load_script(path)
        language = "UA" if path.name.startswith("uk_") else "EN"
        examples.append({"file": path.name, "label": f"{language} · {script['title']}",
                         "text": path.read_text(encoding="utf-8")})
    return examples


EXAMPLES = load_examples()

STYLE = """
:root {
  --bg: #111317; --surface: #181b21; --border: #2a2e36;
  --text: #e6e8ec; --muted: #8b919c; --faint: #5f6570;
  --accent: #93c47d; --accent-hover: #a5d091; --accent-ink: #13200d;
  --danger: #e8938b;
  --font: "Nunito", system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
  color-scheme: dark;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 15px/1.6 var(--font); }
.wrap { max-width: 1280px; margin: 0 auto; padding: 40px 32px; }

/* two columns on wide screens: form on the left (sticky), results on the right */
.layout { display: grid; grid-template-columns: minmax(0, 1fr); gap: 40px; }
@media (min-width: 1000px) {
  .layout { grid-template-columns: minmax(0, 2fr) minmax(0, 3fr); gap: 56px; align-items: start; }
  #gen-form { position: sticky; top: 24px; }
}
h1 { margin: 0 0 28px; font-size: 22px; font-weight: 700; display: flex; align-items: center; gap: 10px; }
.mock-badge { font-size: 11px; font-weight: 700; letter-spacing: 0.08em; color: #e9c46a;
              border: 1px solid #6b5a2e; border-radius: 6px; padding: 1px 7px; }
.small { font-size: 13px; }
.muted { color: var(--muted); }
code { font-family: var(--mono); font-size: 0.9em; }
button, input, select, textarea { font: inherit; color: inherit; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

/* secondary controls: small, quiet */
.tools { display: flex; gap: 8px; margin-bottom: 8px; }
.quiet { background: transparent; border: 1px solid var(--border); border-radius: 8px; color: var(--muted);
         padding: 4px 10px; font-size: 13px; cursor: pointer; }
.quiet:hover { color: var(--text); border-color: #3a3f49; }
select.quiet { appearance: none; -webkit-appearance: none; width: 6.5em; text-align: center; }
textarea, input[type=number], select.field { width: 100%; background: var(--surface); border: 1px solid var(--border);
         border-radius: 10px; padding: 12px 14px; }
textarea::placeholder { color: var(--faint); }
#script { min-height: 280px; resize: vertical; font-family: var(--mono); font-size: 13px; line-height: 1.6; }
#script.dragging { border-style: dashed; border-color: var(--muted); }
.note { min-height: 20px; margin: 6px 0 0; font-size: 13px; color: var(--muted); }
.note.error { color: var(--danger); }

/* settings: collapsed by default */
details.settings { margin: 16px 0 20px; border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); }
details.settings summary { cursor: pointer; padding: 12px 0; color: var(--muted); font-size: 13px; list-style: none; }
details.settings summary::-webkit-details-marker { display: none; }
details.settings summary::before { content: "▸"; display: inline-block; width: 16px; }
details.settings[open] summary::before { content: "▾"; }
details.settings summary b { color: var(--text); font-weight: 600; }
.settings-body { display: grid; gap: 16px; padding: 4px 0 20px; }
.settings-body label, .settings-body legend { display: block; font-size: 13px; color: var(--muted); margin-bottom: 6px; padding: 0; }
fieldset { border: 0; margin: 0; padding: 0; min-width: 0; }
.checks { display: flex; flex-wrap: wrap; gap: 6px 20px; }
.checks label { display: inline-flex; align-items: center; gap: 8px; margin: 0; color: var(--text); font-size: 15px; cursor: pointer; }
.checks input { accent-color: #c9ced6; width: 16px; height: 16px; margin: 0; }
.pair { display: grid; grid-template-columns: 120px 1fr; gap: 16px; }
#context { min-height: 0; font-size: 14px; }

/* the one primary action */
.primary { width: 100%; display: inline-flex; align-items: center; justify-content: center; gap: 10px;
           border: 0; border-radius: 10px; padding: 13px 18px; font-size: 16px; font-weight: 700;
           background: var(--accent); color: var(--accent-ink); cursor: pointer; }
.primary:hover { background: var(--accent-hover); }
.primary:disabled { cursor: progress; opacity: 0.85; }
.spinner { display: none; width: 16px; height: 16px; border-radius: 50%; border: 2px solid rgba(19, 32, 13, 0.3);
           border-top-color: var(--accent-ink); animation: spin 0.8s linear infinite; }
.loading .spinner { display: inline-block; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spinner { animation-duration: 2.4s; } }

/* results */
#results { min-width: 0; }
/* while generating: hide old results, show a quiet spinner in their place */
.loading #results > * { display: none; }
.loading #results::before { content: ""; display: block; width: 22px; height: 22px; margin: 96px auto;
                            border-radius: 50%; border: 2px solid var(--border); border-top-color: var(--muted);
                            animation: spin 0.8s linear infinite; }
.results-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; margin-bottom: 4px; }
.results-head h2 { margin: 0; font-size: 15px; font-weight: 600; }
.variant { padding: 20px 0; border-top: 1px solid var(--border); }
.variant-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; color: var(--muted); font-size: 13px; }
.variant-id { font-family: var(--mono); }
.icon { background: transparent; border: 0; color: var(--faint); padding: 4px; border-radius: 6px; cursor: pointer; line-height: 0; }
.icon:hover, .icon.ok { color: var(--text); }
.scene { display: grid; grid-template-columns: 24px 88px 1fr; gap: 2px 12px; }
.scene + .scene { margin-top: 6px; }
.scene-no, .tag { color: var(--faint); font-size: 13px; }
.line { display: contents; }
.line .text { overflow-wrap: anywhere; justify-self: start; padding: 1px 8px; border-radius: 4px;
              border-left: 2px solid transparent; }
.line.new .text { background: rgba(147, 196, 125, 0.10); border-left-color: rgba(147, 196, 125, 0.6); }
.line.same .text { color: var(--muted); }
details.full { margin-top: 10px; }
details.full summary { cursor: pointer; color: var(--faint); font-size: 13px; }
details.full pre { white-space: pre-wrap; font-family: var(--mono); font-size: 12.5px; color: var(--muted);
                   border-left: 2px solid var(--border); padding-left: 12px; }
.error-card { border: 1px solid #5a3633; border-radius: 10px; padding: 16px 18px; }
.error-card h2 { margin: 0 0 4px; font-size: 15px; font-weight: 600; color: var(--danger); }
.error-card p { margin: 4px 0 0; white-space: pre-line; }

@media (max-width: 560px) {
  .wrap { padding: 28px 16px 32px; }
  .pair { grid-template-columns: 1fr; }
  .scene { grid-template-columns: 20px 1fr; }
  .scene .tag { grid-column: 2; }
  .scene .text { grid-column: 2; margin-bottom: 4px; }
}
"""

SCRIPT = """
var ELEMENT_KEYS = ["hook", "first_lines", "onscreen_text"];
var scriptArea = document.getElementById("script");
var form = document.getElementById("gen-form");
var submit = document.getElementById("submit");

function plural(n, one, few, many) {  // Ukrainian: 1 сцена, 2 сцени, 5 сцен
  var last = n % 10, lastTwo = n % 100;
  if (last === 1 && lastTwo !== 11) return one;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return few;
  return many;
}

// ---------- copy buttons ----------
function copyText(text, button) {
  function done() {
    button.classList.add("ok");
    var old = button.getAttribute("title");
    button.setAttribute("title", "Скопійовано");
    if (!button.classList.contains("icon")) {
      button.setAttribute("data-label", button.getAttribute("data-label") || button.textContent);
      button.textContent = "Скопійовано";
    }
    setTimeout(function () {
      button.classList.remove("ok");
      button.setAttribute("title", old || "");
      if (button.getAttribute("data-label")) button.textContent = button.getAttribute("data-label");
    }, 1500);
  }
  function fallback() {  // older browsers: copy through a temporary textarea
    var area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
    done();
  }
  if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, fallback);
  else fallback();
}

document.addEventListener("click", function (event) {
  var button = event.target.closest("button[data-copy], button[data-copy-all]");
  if (!button) return;
  var text = button.getAttribute("data-copy");
  if (button.hasAttribute("data-copy-all")) {
    var cards = document.querySelectorAll(".variant");
    text = Array.prototype.map.call(cards, function (card) { return card.getAttribute("data-text"); }).join("\\n\\n");
  }
  copyText(text, button);
});

// ---------- settings summary line ----------
function updateSummary() {
  var LABELS = { hook: "хук", first_lines: "перші фрази", onscreen_text: "текст на екрані" };
  var chosen = [];
  document.querySelectorAll('input[name="elements"]').forEach(function (box) {
    if (box.checked) chosen.push(LABELS[box.value]);
  });
  var text = chosen.length ? chosen.join(", ") : "нічого не обрано";
  var parts = [text.charAt(0).toUpperCase() + text.slice(1)];
  var n = parseInt(document.getElementById("n").value, 10) || 0;
  parts.push(n + " " + plural(n, "варіант", "варіанти", "варіантів"));
  var model = document.getElementById("model");
  parts.push(model.options[model.selectedIndex].textContent);
  if (document.getElementById("context").value.trim()) parts.push("з контекстом");
  document.getElementById("summary-values").textContent = parts.join(" · ");
}
form.addEventListener("input", updateSummary);
form.addEventListener("change", updateSummary);

// ---------- import: front matter + script body -> form fields ----------
function showNote(message, isError) {
  var note = document.getElementById("note");
  note.textContent = message;
  note.classList.toggle("error", !!isError);
}

// Same rules as split_front_matter() in script.py.
function parseDocument(text, fileName) {
  text = text.replace(/^\\uFEFF/, "");
  var settings = {}, body = text, title = "", scenes = 0;
  if (text.trim().charAt(0) === "{") {
    var data = JSON.parse(text);  // a broken file throws -> error note
    ["context", "elements", "variants", "model"].forEach(function (key) {
      if (key in data) settings[key] = data[key];
    });
    body = JSON.stringify({ title: data.title || "", scenes: data.scenes || [] }, null, 2);
    title = data.title || "";
    scenes = (data.scenes || []).length;
  } else {
    var lines = text.split(/\\r?\\n/);
    if (lines[0].trim() === "---") {
      for (var end = 1; end < lines.length; end++) {
        if (lines[end].trim() !== "---") continue;
        lines.slice(1, end).forEach(function (line) {
          var colon = line.indexOf(":");  // only the FIRST ':' splits key and value
          if (colon > 0) settings[line.slice(0, colon).trim().toLowerCase()] = line.slice(colon + 1).trim();
        });
        body = lines.slice(end + 1).join("\\n");
        break;
      }
    }
    body.split(/\\r?\\n/).forEach(function (line) {
      var s = line.trim();
      if (s.indexOf("##") === 0) scenes++;
      else if (!title && s.indexOf("# ") === 0) title = s.slice(2).trim();
    });
  }
  return { body: body.trim() + "\\n", settings: settings, title: title || fileName, scenes: scenes };
}

function applyDocument(doc) {
  var s = doc.settings;
  var modelSelect = document.getElementById("model");
  // start from the defaults, then apply what the file says (unknown keys are ignored)
  scriptArea.value = doc.body;
  document.getElementById("context").value = typeof s.context === "string" ? s.context : "";
  var elements = Array.isArray(s.elements) ? s.elements : String(s.elements || "").split(/[,\\s]+/);
  elements = elements.filter(function (e) { return ELEMENT_KEYS.indexOf(e) !== -1; });
  if (elements.length === 0) elements = ELEMENT_KEYS;
  document.querySelectorAll('input[name="elements"]').forEach(function (box) {
    box.checked = elements.indexOf(box.value) !== -1;
  });
  var variants = parseInt(s.variants, 10);
  var nInput = document.getElementById("n");
  nInput.value = variants >= 1 ? Math.min(variants, parseInt(nInput.max, 10)) : nInput.defaultValue;
  if (!modelSelect.disabled) {
    var known = Array.prototype.some.call(modelSelect.options, function (o) { return o.value === s.model; });
    modelSelect.value = known ? s.model : modelSelect.getAttribute("data-default");
  }
  updateSummary();
}

function importText(text, fileName) {
  try {
    var doc = parseDocument(text, fileName);
    applyDocument(doc);
    showNote(doc.title + " · " + doc.scenes + " " + plural(doc.scenes, "сцена", "сцени", "сцен"));
  } catch (error) {
    showNote("Не вдалося прочитати файл: " + error.message, true);
  }
}

function importFile(file) {
  if (file) file.text().then(function (text) { importText(text, file.name); });
}

var fileInput = document.getElementById("import-file");
document.getElementById("import-btn").addEventListener("click", function () { fileInput.click(); });
fileInput.addEventListener("change", function () {
  importFile(fileInput.files[0]);
  fileInput.value = "";  // allow importing the same file again
});

function hasFiles(event) {
  return event.dataTransfer && Array.prototype.indexOf.call(event.dataTransfer.types, "Files") !== -1;
}
scriptArea.addEventListener("dragover", function (event) {
  if (!hasFiles(event)) return;
  event.preventDefault();
  scriptArea.classList.add("dragging");
});
scriptArea.addEventListener("dragleave", function () { scriptArea.classList.remove("dragging"); });
scriptArea.addEventListener("drop", function (event) {
  scriptArea.classList.remove("dragging");
  if (!hasFiles(event)) return;  // plain text drops behave as usual
  event.preventDefault();
  importFile(event.dataTransfer.files[0]);
});
// a file dropped next to the text area should not make the browser open it
window.addEventListener("dragover", function (event) { if (hasFiles(event)) event.preventDefault(); });
window.addEventListener("drop", function (event) { if (hasFiles(event)) event.preventDefault(); });

var examples = JSON.parse(document.getElementById("examples-data").textContent);
var exampleSelect = document.getElementById("examples");
exampleSelect.addEventListener("change", function () {
  var example = examples[exampleSelect.value];
  if (example) importText(example.text, example.file);
  exampleSelect.value = "";  // the control always reads "Приклади"
});

// ---------- loading state ----------
form.addEventListener("submit", function () {
  submit.disabled = true;  // the page reloads with the result, so this resets itself
  submit.querySelector(".label").textContent = submit.getAttribute("data-wait");
  document.body.classList.add("loading");
});
window.addEventListener("pageshow", function () {  // coming back with the Back button
  submit.disabled = false;
  submit.querySelector(".label").textContent = "Згенерувати";
  document.body.classList.remove("loading");
});

// after a generation on a narrow screen (results are below the form), bring them into view
if (document.querySelector(".variant, .error-card") && window.matchMedia("(max-width: 999px)").matches) {
  document.getElementById("results").scrollIntoView({ behavior: "smooth", block: "start" });
}
"""


def esc(value):
    return html.escape(str(value), quote=True)


def plural(n, one, few, many):
    """Ukrainian plural: 1 варіант, 2 варіанти, 5 варіантів."""
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def model_options(default_model):
    options = list(MODEL_OPTIONS)
    if default_model not in [value for value, _ in options]:
        options.insert(0, (default_model, default_model))
    return options


def settings_summary(elements, n, model_label, has_context):
    """One line shown on the closed «Налаштування» section."""
    labels = [ELEMENT_LABELS[e].lower() for e in ELEMENT_LABELS if e in elements]
    text = ", ".join(labels) if labels else "нічого не обрано"
    parts = [text[0].upper() + text[1:], f"{n} {plural(n, 'варіант', 'варіанти', 'варіантів')}", model_label]
    if has_context:
        parts.append("з контекстом")
    return " · ".join(parts)


def render_form(form, backend, model):
    chosen = form.get("elements", list(ELEMENT_LABELS))
    checks = "".join(
        f'<label><input type="checkbox" name="elements" value="{key}"{" checked" if key in chosen else ""}> {label}</label>'
        for key, label in ELEMENT_LABELS.items()
    )
    if backend == "mock":
        model_label = "mock"
        model_field = '<select id="model" class="field" disabled><option>mock</option></select>'
    else:
        selected_model = form.get("model", model)
        options = model_options(model)
        model_label = dict(options).get(selected_model, selected_model)
        model_field = f'<select id="model" name="model" class="field" data-default="{esc(model)}">' + "".join(
            f'<option value="{esc(value)}"{" selected" if value == selected_model else ""}>{esc(label)}</option>'
            for value, label in options
        ) + "</select>"
    try:
        n = int(form.get("n", config.DEFAULT_VARIANTS))
    except ValueError:
        n = config.DEFAULT_VARIANTS
    summary = settings_summary(chosen, n, model_label, bool(form.get("context", "").strip()))
    example_options = "".join(f'<option value="{index}">{esc(example["label"])}</option>'
                              for index, example in enumerate(EXAMPLES))
    placeholder = "# Назва&#10;## Scene 1&#10;VO: ...&#10;On-screen: ..."
    return f"""
<form id="gen-form" method="post" action="/generate">
  <div class="tools">
    <select id="examples" class="quiet" aria-label="Приклади"><option value="">Приклади</option>{example_options}</select>
    <button type="button" class="quiet" id="import-btn">Імпортувати сценарій</button>
    <input type="file" id="import-file" accept=".md,.markdown,.txt,.json,text/markdown,text/plain,application/json" hidden>
  </div>
  <textarea id="script" name="script" required spellcheck="false" aria-label="Сценарій" placeholder="{placeholder}">{esc(form.get("script", ""))}</textarea>
  <p id="note" class="note" aria-live="polite"></p>
  <details class="settings">
    <summary>Налаштування: <b id="summary-values">{esc(summary)}</b></summary>
    <div class="settings-body">
      <fieldset>
        <legend>Що змінювати</legend>
        <div class="checks">{checks}</div>
      </fieldset>
      <div class="pair">
        <div><label for="n">Варіантів</label>
          <input id="n" type="number" name="n" min="1" max="{config.MAX_VARIANTS}" value="{esc(form.get("n", config.DEFAULT_VARIANTS))}"></div>
        <div><label for="model">Модель</label>{model_field}</div>
      </div>
      <div><label for="context">Контекст</label>
        <textarea id="context" name="context" rows="2" placeholder="Продукт, аудиторія, мова">{esc(form.get("context", ""))}</textarea></div>
    </div>
  </details>
  <button class="primary" id="submit" type="submit" data-wait="Генеруємо…">
    <span class="spinner" aria-hidden="true"></span><span class="label">Згенерувати</span>
  </button>
</form>"""


def variant_lines(generation, variant):
    """[(scene number, "VO"/"On-screen", text, changed?)] for the rewritten elements only."""
    original = generation["input_script"]["scenes"]
    elements = generation["elements"]
    lines = []
    for index, scene in enumerate(variant["script"]["scenes"]):
        voiceover_rewritten = (index == 0 and "hook" in elements) or \
                              (1 <= index <= FIRST_LINES_SCENES and "first_lines" in elements)
        if voiceover_rewritten:
            lines.append((index + 1, "VO", scene["voiceover"], scene["voiceover"] != original[index]["voiceover"]))
        if "onscreen_text" in elements:
            lines.append((index + 1, "On-screen", scene["onscreen_text"],
                          scene["onscreen_text"] != original[index]["onscreen_text"]))
    return lines


def render_variant(generation, variant):
    lines = variant_lines(generation, variant)
    copy_text = "\n".join([f"{variant['id']} ({variant['angle']})"] +
                          [f"Сцена {number} · {tag}: {text}" for number, tag, text, _ in lines])
    scenes_html = ""
    for number in sorted({line[0] for line in lines}):
        rows = ""
        scene_lines = [line for line in lines if line[0] == number]
        for position, (_, tag, text, changed) in enumerate(scene_lines):
            label = number if position == 0 else ""
            rows += (f'<span class="scene-no">{label}</span><span class="line {"new" if changed else "same"}">'
                     f'<span class="tag">{tag}</span><span class="text">{esc(text) or "—"}</span></span>')
        scenes_html += f'<div class="scene">{rows}</div>'
    return f"""
<article class="variant" data-text="{esc(copy_text)}">
  <div class="variant-head">
    <span class="variant-id">{esc(variant["id"])}</span>
    <button type="button" class="icon" data-copy="{esc(variant["id"])}" title="Копіювати ID" aria-label="Копіювати ID">{COPY_ICON}</button>
    <span>· {esc(variant["angle"])}</span>
  </div>
  {scenes_html}
  <details class="full"><summary>Повний сценарій</summary><pre>{esc(script_mod.to_markdown(variant["script"]))}</pre></details>
</article>"""


def render_variants(generation):
    g = generation
    count = len(g["variants"])
    note = ""
    if count < g["requested"]:
        note = f'<p class="small muted">Модель повернула {count} з {g["requested"]}.</p>'
    cards = "".join(render_variant(g, variant) for variant in g["variants"])
    return f"""
<div class="results-head">
  <h2>{count} {plural(count, "варіант", "варіанти", "варіантів")}</h2>
  <button type="button" class="quiet" data-copy-all>Копіювати все</button>
</div>
<p class="small muted">{esc(g["id"])} · {esc(g["model"])} · підсвічено — новий текст</p>
{note}
{cards}"""


def render_error(error, backend):
    if isinstance(error, GenerationError) and backend == "cli":
        hint = ("Перевірте вхід у Claude Code: <code>claude auth status</code> "
                "(якщо ні — <code>claude</code>, потім <code>/login</code>). "
                "Офлайн-демо: <code>python -m socklock serve --mock</code>.")
    elif isinstance(error, GenerationError):
        hint = "Перевірте <code>ANTHROPIC_API_KEY</code> або запустіть сервер з <code>--backend cli</code>."
    else:
        hint = ("Формат: <code>## Scene N</code>, далі <code>VO: ...</code> і <code>On-screen: ...</code>. "
                "Готові сценарії є у списку «Приклади».")
    return (f'<div class="error-card" role="alert"><h2>Не вдалося згенерувати</h2>'
            f'<p>{esc(error)}</p><p class="small muted">{hint}</p></div>')


def examples_json():
    """Examples as JSON inside a <script> tag; '</' is escaped so a text cannot close the tag."""
    return json.dumps(EXAMPLES, ensure_ascii=False).replace("</", "<\\/")


def render_page(form=None, result="", backend="cli", model=config.DEFAULT_MODEL):
    form = form or {}
    badge = ' <span class="mock-badge">MOCK</span>' if backend == "mock" else ""
    return f"""<!doctype html>
<html lang="uk">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SockLock Hooks</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONT_URL}">
<style>{STYLE}</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>SockLock Hooks{badge}</h1>
  </header>
  <main class="layout">
    {render_form(form, backend, model)}
    <section id="results" aria-live="polite">{result}</section>
  </main>
</div>
<script type="application/json" id="examples-data">{examples_json()}</script>
<script>{SCRIPT}</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    backend = "cli"  # set by serve()
    model = config.DEFAULT_MODEL

    def send_html(self, body, status=200):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path != "/":
            self.send_html("<p>Not found</p>", status=404)
            return
        self.send_html(render_page(backend=self.backend, model=self.model))

    def do_POST(self):
        if self.path != "/generate":
            self.send_html("<p>Not found</p>", status=404)
            return
        length = int(self.headers.get("Content-Length", 0))
        fields = parse_qs(self.rfile.read(length).decode("utf-8"))
        form = {key: values[0] for key, values in fields.items()}
        form["elements"] = fields.get("elements", [])
        allowed_models = [value for value, _ in model_options(self.model)]
        model = form.get("model") if form.get("model") in allowed_models else self.model
        try:
            script = script_mod.parse_script_text(form.get("script", ""), fallback_title="Pasted script")
            context = {"context": form.get("context", "")}
            generation = generator.generate(script, form["elements"], int(form.get("n") or 10), context,
                                            backend=self.backend, model=model)
            result = render_variants(generation)
        except (ValueError, GenerationError) as error:
            result = render_error(error, self.backend)
        self.send_html(render_page(form, result, self.backend, self.model))


def serve(port=8000, backend="cli", model=config.DEFAULT_MODEL):
    Handler.backend = backend
    Handler.model = model
    # One thread per request: an idle browser connection or a 15 s generation does not block other requests.
    # Thread-safe storage: storage.open_db() opens its own SQLite connection on every call.
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)  # local only, not exposed to the network
    server.daemon_threads = True  # Ctrl+C does not wait for open connections
    print(f"Відкрийте http://127.0.0.1:{port}  (backend: {backend}, модель: {model}). Ctrl+C — зупинити.",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nЗупинено.")
    finally:
        server.server_close()
