"""How we talk to the model. Three backends, all return the same thing:

    (data, served_model, usage)
    data = {"variants": [{"angle": str, "hook": str, "first_lines": [str], "onscreen_text": [str]}, ...]}

- cli  (default): the local Claude Code CLI (`claude -p`), runs on the user's Claude subscription.
- api  : the official `anthropic` Python SDK with an API key (for the future production Slack bot).
- mock : an offline FAKE generator for tests and the demo. Only used when asked for explicitly.
"""
import json
import subprocess

# The JSON shape we ask the model for. The same schema is used by the CLI (--json-schema)
# and by the API (structured outputs). It never changes, so the prompt prefix stays cacheable.
# For elements the user did not choose, the model returns "" or [] and we ignore them.
VARIANTS_SCHEMA = {
    "type": "object",
    "properties": {
        "variants": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "angle": {"type": "string"},
                    "hook": {"type": "string"},
                    "first_lines": {"type": "array", "items": {"type": "string"}},
                    "onscreen_text": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["angle", "hook", "first_lines", "onscreen_text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["variants"],
    "additionalProperties": False,
}

BACKENDS = ("cli", "api", "mock")
CLI_TIMEOUT_SECONDS = 300
API_MAX_TOKENS = 16000


class GenerationError(Exception):
    """A problem the user should see (no login, refusal, timeout...). Nothing is saved."""


def validate_variants(data):
    """Raise ValueError if the model answer does not have the expected shape."""
    if not isinstance(data, dict) or not isinstance(data.get("variants"), list):
        raise ValueError("у відповіді немає списку 'variants'")
    for variant in data["variants"]:
        if not isinstance(variant, dict):
            raise ValueError("варіант не є об'єктом")
        if not isinstance(variant.get("hook"), str) or not isinstance(variant.get("angle"), str):
            raise ValueError("у варіанті немає рядків 'hook'/'angle'")
        for key in ("first_lines", "onscreen_text"):
            items = variant.get(key)
            if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
                raise ValueError(f"'{key}' має бути списком рядків")
    return data


def extract_json(text):
    """Find the JSON object inside a text answer (it may be wrapped in ```json fences)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("у тексті відповіді немає JSON")
    return json.loads(text[start:end + 1])


# ---------------------------------------------------------------- cli backend

def build_cli_command(system_text, model, effort):
    return [
        "claude", "-p",                      # headless "print" mode: one answer, then exit
        "--output-format", "json",           # machine-readable envelope with the result
        "--model", model,                    # e.g. claude-sonnet-5-5, sonnet, opus
        "--effort", effort,                  # low / medium / high
        "--json-schema", json.dumps(VARIANTS_SCHEMA),  # structured output
        "--system-prompt", system_text,      # our stable prefix replaces Claude Code's own prompt
        "--tools", "",                       # NO tools: text generation only, no files, no shell
        "--strict-mcp-config",               # ignore the user's MCP servers
        "--safe-mode",                       # ignore personal CLAUDE.md, skills, hooks, plugins
        "--no-session-persistence",          # do not store these runs as Claude Code sessions
    ]


def parse_cli_output(stdout):
    """`claude -p --output-format json` prints one JSON envelope. Take the variants out of it."""
    envelope = json.loads(stdout)  # JSONDecodeError is a ValueError -> retried by the caller
    if envelope.get("is_error"):
        message = str(envelope.get("result", ""))[:500]
        raise GenerationError(
            f"Claude Code повернув помилку: {message}\n"
            "Перевірте вхід: запустіть `claude` у терміналі та виконайте /login."
        )
    if envelope.get("stop_reason") == "refusal":
        raise GenerationError("Claude відмовився виконати запит (refusal). Нічого не збережено.")
    data = envelope.get("structured_output")
    if data is None:  # older CLI versions: the JSON is inside the text result
        data = extract_json(str(envelope.get("result", "")))
    validate_variants(data)
    served_model = next(iter(envelope.get("modelUsage") or {}), None)
    raw_usage = envelope.get("usage") or {}
    usage = {key: raw_usage.get(key, 0) for key in (
        "input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
    usage["cost_usd_list_price"] = envelope.get("total_cost_usd")
    return data, served_model, usage


def call_cli(system_text, user_text, model, effort, run=None):
    """Run `claude -p`. The user message goes in via stdin (it can be long).

    `run` defaults to subprocess.run; tests pass a fake one so no real process is started.
    """
    run = run or subprocess.run
    command = build_cli_command(system_text, model, effort)
    last_error = None
    for _attempt in range(2):  # one retry if the answer cannot be parsed
        try:
            completed = run(command, input=user_text, capture_output=True,
                            text=True, timeout=CLI_TIMEOUT_SECONDS)
        except FileNotFoundError as error:
            raise GenerationError(
                "Не знайдено Claude Code CLI (`claude`). Встановіть його та увійдіть (`claude`, потім /login), "
                "або запустіть з --mock для офлайн-демо."
            ) from error
        except subprocess.TimeoutExpired as error:
            raise GenerationError(
                f"Claude Code не відповів за {CLI_TIMEOUT_SECONDS} с. Спробуйте менше варіантів."
            ) from error
        if completed.returncode != 0 and not completed.stdout.strip():
            raise GenerationError(
                f"`claude` завершився з кодом {completed.returncode}: {completed.stderr.strip()[:500]}"
            )
        try:
            return parse_cli_output(completed.stdout)
        except ValueError as error:
            last_error = error
    raise GenerationError(f"Не вдалося розібрати відповідь Claude Code після 2 спроб: {last_error}")


# ---------------------------------------------------------------- api backend

def call_api(system_text, user_text, model, effort, client=None):
    """Official anthropic SDK. Needs an API key (ANTHROPIC_API_KEY or an `ant auth login` profile)."""
    import anthropic  # imported here so the cli/mock backends work without the package

    client = client or anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=model,
            max_tokens=API_MAX_TOKENS,
            # Server-side fallback: if a safety classifier declines, the API retries on a
            # recommended model inside the same call.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={
                "effort": effort,
                "format": {"type": "json_schema", "schema": VARIANTS_SCHEMA},
            },
            # The style library is the stable prefix -> cache it (cheaper and faster on repeat runs).
            system=[{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_text}],
        )
    except TypeError as error:
        # The SDK raises TypeError before sending anything when it finds no credentials.
        if "authentication" in str(error):
            raise GenerationError(
                "Немає API-ключа Anthropic. Задайте ANTHROPIC_API_KEY або використайте --backend cli."
            ) from error
        raise
    except anthropic.AuthenticationError as error:
        raise GenerationError("API-ключ Anthropic недійсний.") from error
    except anthropic.NotFoundError as error:
        raise GenerationError(f"Модель '{model}' не знайдена.") from error
    except anthropic.RateLimitError as error:
        raise GenerationError("Перевищено ліміт запитів API. Спробуйте пізніше.") from error
    except anthropic.APIStatusError as error:
        raise GenerationError(f"Помилка API {error.status_code}: {error.message}") from error
    except anthropic.APIConnectionError as error:
        raise GenerationError("Немає з'єднання з API Anthropic.") from error

    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise GenerationError(f"Claude відмовився виконати запит (категорія: {category}). Нічого не збережено.")
    if response.stop_reason == "max_tokens":
        raise GenerationError("Відповідь обрізана (max_tokens). Попросіть менше варіантів.")
    # With adaptive thinking the answer can start with a thinking block: read blocks by type.
    text = next((block.text for block in response.content if block.type == "text"), "")
    try:
        data = validate_variants(json.loads(text))
    except ValueError as error:
        raise GenerationError(f"Модель повернула некоректний JSON: {error}") from error
    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cache_read_input_tokens": response.usage.cache_read_input_tokens or 0,
        "cache_creation_input_tokens": response.usage.cache_creation_input_tokens or 0,
    }
    return data, response.model, usage


# ---------------------------------------------------------------- mock backend

MOCK_ANGLES = ["pain point", "personal result", "frustration", "curiosity", "quick demo",
               "social proof", "life hack", "humor", "listicle", "call-out"]
MOCK_HOOKS = [
    "POV: your dryer just ate your last matching sock.",
    "I haven't lost a single sock in six months.",
    "Stop buying socks that break up after one wash.",
    "This is why your socks keep disappearing.",
    "Matching socks in two seconds. Watch.",
    "My husband laughed at my magnetic socks. Then he stole a pair.",
    "The sock drawer trick nobody told you about.",
    "Odd socks are a choice. Here's the fix.",
    "Three reasons I switched to magnetic socks.",
    "If you hate folding socks, you need to see this.",
]
MOCK_LINES = [
    "Tiny magnets in the cuff snap each pair together.",
    "Throw them in the wash. They come out as pairs.",
    "No more digging through a pile of lonely socks.",
    "You don't feel the magnets. You just stop losing socks.",
    "Five pairs for $29, then a fresh set every quarter.",
]
MOCK_ONSCREEN = ["SOCKS THAT STICK TOGETHER", "NO MORE ODD SOCKS", "SNAP. WASH. DONE.",
                 "PAIRS STAY PAIRS", "5 PAIRS FOR $29", "MAGNETS IN THE CUFF"]


def mock_variants(n, n_first_lines, n_scenes, elements):
    """FAKE deterministic 'model output' with the same shape as Claude's JSON. Not AI text."""
    variants = []
    for i in range(n):
        k = i % len(MOCK_HOOKS)
        variants.append({
            "angle": f"[MOCK] {MOCK_ANGLES[k]}",
            "hook": MOCK_HOOKS[k] if "hook" in elements else "",
            "first_lines": [MOCK_LINES[(i + j) % len(MOCK_LINES)] for j in range(n_first_lines)]
            if "first_lines" in elements else [],
            "onscreen_text": [MOCK_ONSCREEN[(i + j) % len(MOCK_ONSCREEN)] for j in range(n_scenes)]
            if "onscreen_text" in elements else [],
        })
    return {"variants": variants}, "mock", {}
