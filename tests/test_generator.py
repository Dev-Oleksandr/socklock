"""generate() with a mocked model: a fake subprocess.run for the cli backend and a fake
anthropic client for the api backend. No real calls are made."""
import json
import subprocess
from types import SimpleNamespace

import pytest

from socklock import backends, generator, storage
from socklock import script as script_mod
from socklock.backends import GenerationError

SCRIPT = script_mod.parse_script_text("""# Laundry day
## Scene 1
Visual: Dryer
VO: I lose a sock every wash.
On-screen: WHERE DO THEY GO
## Scene 2
VO: So I tried magnetic socks.
On-screen: MAGNETS
## Scene 3
VO: They come out as a pair.
On-screen: STILL A PAIR
## Scene 4
VO: Five pairs for $29.
On-screen: 5 PAIRS FOR $29
""")


def model_answer(n):
    return {"variants": [
        {"angle": f"angle {i}", "hook": f"Hook {i}", "first_lines": [f"L2 {i}", f"L3 {i}"],
         "onscreen_text": [f"OS{j} {i}" for j in range(1, 5)]}
        for i in range(1, n + 1)
    ]}


def cli_envelope(data):
    """What `claude -p --output-format json` prints."""
    return json.dumps({
        "type": "result", "subtype": "success", "is_error": False,
        "result": json.dumps(data), "structured_output": data,
        "modelUsage": {"claude-sonnet-5-5": {"inputTokens": 10}},
        "usage": {"input_tokens": 10, "output_tokens": 500,
                  "cache_read_input_tokens": 1200, "cache_creation_input_tokens": 0},
        "total_cost_usd": 0.01,
    })


class FakeRun:
    """Stands in for subprocess.run and returns prepared stdouts one after another."""

    def __init__(self, *stdouts, returncode=0):
        self.stdouts = list(stdouts)
        self.returncode = returncode
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append({"command": command, **kwargs})
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdouts.pop(0), stderr="")


@pytest.fixture
def paths(tmp_path):
    library_dir = tmp_path / "library"
    (library_dir / "winners").mkdir(parents=True)
    (library_dir / "style_guide.md").write_text("Banned words: miracle.", encoding="utf-8")
    (library_dir / "winners" / "w1.md").write_text("# Winner one\n## Scene 1\nVO: Old hook", encoding="utf-8")
    return {"library_dir": library_dir, "db_path": tmp_path / "test.db", "out_dir": tmp_path / "out"}


def test_generate_with_cli_backend(paths):
    run = FakeRun(cli_envelope(model_answer(3)))
    gen = generator.generate(SCRIPT, ["hook", "onscreen_text"], 3, {"product": "socks", "angle": ""},
                             backend="cli", model="claude-sonnet-5-5", run=run, **paths)

    # what we sent to `claude -p`
    call = run.calls[0]
    command = call["command"]
    assert command[:2] == ["claude", "-p"]
    assert command[command.index("--model") + 1] == "claude-sonnet-5-5"
    assert command[command.index("--effort") + 1] == "medium"
    assert command[command.index("--tools") + 1] == ""  # no tools at all
    assert json.loads(command[command.index("--json-schema") + 1]) == backends.VARIANTS_SCHEMA
    system_prompt = command[command.index("--system-prompt") + 1]
    assert "Banned words: miracle." in system_prompt and "Old hook" in system_prompt
    assert "Write 3 variants" in call["input"]  # user message goes via stdin
    assert "Product: socks" in call["input"] and "Angle:" not in call["input"]  # empty context dropped
    assert call["timeout"] == backends.CLI_TIMEOUT_SECONDS

    # IDs, structure, only chosen elements changed
    assert [v["id"] for v in gen["variants"]] == [f"{gen['id']}-v{i}" for i in (1, 2, 3)]
    first = gen["variants"][0]["script"]
    assert first["scenes"][0]["voiceover"] == "Hook 1"
    assert first["scenes"][1]["voiceover"] == "So I tried magnetic socks."  # first_lines not chosen
    assert [s["onscreen_text"] for s in first["scenes"]] == ["OS1 1", "OS2 1", "OS3 1", "OS4 1"]
    assert len(first["scenes"]) == len(SCRIPT["scenes"])

    # saved to SQLite and to files
    assert storage.generation_exists(paths["db_path"], gen["id"])
    assert storage.get_variant(paths["db_path"], gen["id"] + "-v2")["script"]["scenes"][0]["voiceover"] == "Hook 2"
    assert gen["served_model"] == "claude-sonnet-5-5"
    assert gen["usage"]["cache_read_input_tokens"] == 1200
    md_file, json_file = gen["files"]
    assert gen["id"] + "-v3" in open(md_file, encoding="utf-8").read()
    assert json.load(open(json_file, encoding="utf-8"))["id"] == gen["id"]


def test_cli_retries_once_on_bad_output(paths):
    run = FakeRun("this is not json", cli_envelope(model_answer(2)))
    gen = generator.generate(SCRIPT, ["hook"], 2, backend="cli", run=run, **paths)
    assert len(run.calls) == 2
    assert len(gen["variants"]) == 2


def test_cli_gives_up_after_two_bad_outputs_and_saves_nothing(paths):
    bad = json.dumps({"is_error": False, "result": "sorry, no json here"})
    with pytest.raises(GenerationError, match="2"):
        generator.generate(SCRIPT, ["hook"], 2, backend="cli", run=FakeRun(bad, bad), **paths)
    assert storage.pilot_stats(paths["db_path"])["generated"] == 0


def test_cli_reads_json_from_text_result_when_no_structured_output(paths):
    data = model_answer(1)
    envelope = json.dumps({"is_error": False, "result": "```json\n" + json.dumps(data) + "\n```"})
    gen = generator.generate(SCRIPT, ["hook"], 1, backend="cli", run=FakeRun(envelope), **paths)
    assert gen["variants"][0]["script"]["scenes"][0]["voiceover"] == "Hook 1"


def test_cli_error_is_not_replaced_by_mock(paths):
    not_logged_in = json.dumps({"is_error": True, "result": "Not logged in. Please run /login"})
    with pytest.raises(GenerationError, match="login"):
        generator.generate(SCRIPT, ["hook"], 2, backend="cli", run=FakeRun(not_logged_in), **paths)
    assert storage.pilot_stats(paths["db_path"])["mock_generations"] == 0


def test_cli_not_installed(paths):
    def missing(*args, **kwargs):
        raise FileNotFoundError("claude")
    with pytest.raises(GenerationError, match="Claude Code CLI"):
        generator.generate(SCRIPT, ["hook"], 2, backend="cli", run=missing, **paths)


def test_cli_timeout(paths):
    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired("claude", 300)
    with pytest.raises(GenerationError, match="300"):
        generator.generate(SCRIPT, ["hook"], 2, backend="cli", run=slow, **paths)


def test_cli_trims_extra_variants(paths):
    gen = generator.generate(SCRIPT, ["hook"], 2, backend="cli", run=FakeRun(cli_envelope(model_answer(5))), **paths)
    assert len(gen["variants"]) == 2


# ------------------------------------------------------------ api backend with a fake client

class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def fake_client(stop_reason="end_turn", data=None, stop_details=None):
    content = [SimpleNamespace(type="thinking", thinking=""),  # adaptive thinking block comes first
               SimpleNamespace(type="text", text=json.dumps(data or model_answer(2)))]
    usage = SimpleNamespace(input_tokens=50, output_tokens=400,
                            cache_read_input_tokens=0, cache_creation_input_tokens=1500)
    response = SimpleNamespace(stop_reason=stop_reason, stop_details=stop_details, content=content,
                               usage=usage, model="claude-sonnet-5-5")
    return SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages(response)))


def test_generate_with_api_backend(paths):
    client = fake_client()
    gen = generator.generate(SCRIPT, ["first_lines"], 2, backend="api", model="claude-sonnet-5-5",
                             client=client, **paths)
    kwargs = client.beta.messages.kwargs
    assert kwargs["model"] == "claude-sonnet-5-5"
    assert kwargs["output_config"]["effort"] == "medium"
    assert kwargs["output_config"]["format"] == {"type": "json_schema", "schema": backends.VARIANTS_SCHEMA}
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["fallbacks"] == "default"
    assert kwargs["betas"] == ["server-side-fallback-2026-07-01"]
    scenes = gen["variants"][1]["script"]["scenes"]
    assert [s["voiceover"] for s in scenes[:3]] == ["I lose a sock every wash.", "L2 2", "L3 2"]


def test_api_refusal_raises_and_saves_nothing(paths):
    client = fake_client(stop_reason="refusal", stop_details=SimpleNamespace(category="general_harms"))
    with pytest.raises(GenerationError, match="general_harms"):
        generator.generate(SCRIPT, ["hook"], 2, backend="api", client=client, **paths)
    assert storage.pilot_stats(paths["db_path"])["generated"] == 0


# ------------------------------------------------------------ mock backend

def test_mock_backend_is_labeled(paths):
    gen = generator.generate(SCRIPT, n=4, backend="mock", **paths)
    assert gen["model"] == "mock" and gen["backend"] == "mock"
    assert all(v["angle"].startswith("[MOCK]") for v in gen["variants"])
    assert "MOCK" in open(gen["files"][0], encoding="utf-8").read()


def test_bad_requests(paths):
    with pytest.raises(ValueError):
        generator.generate(SCRIPT, ["subject_line"], 2, backend="mock", **paths)
    with pytest.raises(ValueError):
        generator.generate(SCRIPT, [], 2, backend="mock", **paths)
    with pytest.raises(ValueError):
        generator.generate(SCRIPT, ["hook"], 0, backend="mock", **paths)
    with pytest.raises(ValueError):
        generator.generate(SCRIPT, ["hook"], 2, backend="nonsense", **paths)


def test_resolve_backend(monkeypatch):
    from socklock import config
    monkeypatch.delenv("SOCKLOCK_MOCK", raising=False)
    assert config.resolve_backend("api") == "api"
    assert config.resolve_backend("api", mock=True) == "mock"
    monkeypatch.setenv("SOCKLOCK_MOCK", "1")
    assert config.resolve_backend("cli") == "mock"
