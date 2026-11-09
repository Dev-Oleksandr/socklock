"""The web page HTML: form, status line, variant cards, errors, escaping. No server is started."""
from socklock import generator, web
from socklock import script as script_mod
from socklock.backends import GenerationError

SCRIPT = script_mod.parse_script_text("""# Test
## Scene 1
VO: Old hook
On-screen: OLD ONE
## Scene 2
VO: Old line two
On-screen: OLD TWO
## Scene 3
VO: Old line three
On-screen: OLD THREE
""")


def mock_generation(tmp_path, elements):
    return generator.generate(SCRIPT, elements, 2, backend="mock", db_path=tmp_path / "t.db",
                              library_dir=tmp_path / "lib", out_dir=tmp_path / "out")


def test_page_has_form_and_status():
    page = web.render_page(backend="cli", model="claude-sonnet-5-5")
    assert "<h1>SockLock Hooks</h1>" in page
    assert 'name="elements" value="first_lines" checked' in page
    assert '<option value="claude-opus-5-5">Opus 5.5</option>' in page
    assert '<main class="layout">' in page and "@media (min-width: 1000px)" in web.STYLE  # two columns
    assert 'class="subtitle"' not in page and "<footer>" not in page  # no explanatory text or status line
    assert 'data-wait="Генеруємо…"' in page and "~15" not in page    # loading text without a time estimate
    assert "Налаштування: <b id=\"summary-values\">Хук, перші фрази, текст на екрані · 10 варіантів · Sonnet 5.5</b>" in page
    assert '<details class="settings">' in page  # settings are collapsed by default
    assert "Nunito" in page and "system-ui" in page  # web font with an offline fallback
    assert 'id="import-btn"' in page and 'accept=".md,.markdown,.txt,.json' in page
    assert '<textarea id="context" name="context"' in page


def test_examples_are_embedded():
    assert len(web.EXAMPLES) == 6
    page = web.render_page()
    assert page.count('<option value="') >= 6 + 2  # 6 examples + 2 models
    assert "UA · День прання без втрат" in page and "EN · Gym bag sock problem" in page
    assert "</script>" not in web.examples_json()  # cannot break out of the <script> tag


def test_mock_page_shows_badge_and_no_model_choice():
    page = web.render_page(backend="mock")
    assert '<span class="mock-badge">MOCK</span>' in page
    assert '<select id="model" class="field" disabled>' in page


def test_user_text_is_escaped():
    page = web.render_page({"script": "<script>alert(1)</script>", "elements": ["hook"]})
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert 'value="first_lines" checked' not in page  # unchecked chips stay unchecked


def test_variant_cards(tmp_path):
    gen = mock_generation(tmp_path, ["hook", "onscreen_text"])
    result = web.render_variants(gen)
    assert result.count('class="variant"') == 2
    assert f'data-copy="{gen["id"]}-v1"' in result and "Копіювати ID" in result
    assert "data-copy-all" in result and "Копіювати все" in result
    assert "MOCK" in result  # the angle of a mock variant is labelled
    # scene 2 voiceover was not chosen, so it is not shown; on-screen text of every scene is
    lines = web.variant_lines(gen, gen["variants"][0])
    assert [(number, tag) for number, tag, _, _ in lines] == [
        (1, "VO"), (1, "On-screen"), (2, "On-screen"), (3, "On-screen")]
    assert all(changed for _, _, _, changed in lines)  # mock texts differ from the original
    assert 'class="line new"' in result
    assert "підсвічено — новий текст" in result                   # short legend under the heading
    assert "rgba(147, 196, 125, 0.10)" in web.STYLE                # soft highlight for new text


def test_error_card_hints():
    cli_error = web.render_error(GenerationError("Not logged in"), "cli")
    assert 'role="alert"' in cli_error and "claude auth status" in cli_error
    script_error = web.render_error(ValueError("no scenes"), "cli")
    assert "## Scene N" in script_error and "claude auth status" not in script_error
    assert "Приклади" in script_error


def test_settings_summary_and_plural():
    assert web.settings_summary(["onscreen_text"], 1, "Opus 5.5", True) == "Текст на екрані · 1 варіант · Opus 5.5 · з контекстом"
    assert web.settings_summary([], 3, "mock", False) == "Нічого не обрано · 3 варіанти · mock"
    assert [web.plural(n, "a", "b", "c") for n in (1, 2, 5, 11, 12, 21, 24)] == ["a", "b", "c", "c", "c", "a", "b"]
