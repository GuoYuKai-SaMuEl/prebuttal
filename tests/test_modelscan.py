from prebuttal import cli
from prebuttal.modelscan import (
    ModelListing,
    anthropic_models,
    gemini_models,
    openai_models,
    render,
    scan,
)


def _patch_get(monkeypatch, by_url: dict):
    """Mimic modelscan._get's contract: return parsed JSON (a dict), not a response."""
    import prebuttal.modelscan as ms

    def fake_get(url, headers=None):
        return by_url[url]

    monkeypatch.setattr(ms, "_get", fake_get)


def test_gemini_models_filters_to_generate_content(monkeypatch):
    _patch_get(
        monkeypatch,
        {
            "https://generativelanguage.googleapis.com/v1beta/models": {
                "models": [
                    {
                        "name": "models/gemini-2.5-flash",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                    {
                        "name": "models/gemini-2.5-pro",
                        "supportedGenerationMethods": ["generateContent", "countTokens"],
                    },
                    {
                        "name": "models/text-embedding-004",
                        "supportedGenerationMethods": ["embedContent"],
                    },
                    {
                        "name": "models/gemini-2.5-flash-image",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                ]
            }
        },
    )
    assert gemini_models("k") == ["gemini-2.5-flash", "gemini-2.5-pro"]


def test_openai_models_filters_noise(monkeypatch):
    _patch_get(
        monkeypatch,
        {
            "https://api.openai.com/v1/models": {
                "data": [
                    {"id": "gpt-4.1-mini"},
                    {"id": "o3-mini"},
                    {"id": "text-embedding-3-small"},
                    {"id": "dall-e-3"},
                    {"id": "whisper-1"},
                    {"id": "gpt-4o-mini-audio-preview"},
                ]
            }
        },
    )
    assert openai_models("k") == ["gpt-4.1-mini", "o3-mini"]


def test_anthropic_models(monkeypatch):
    _patch_get(
        monkeypatch,
        {"https://api.anthropic.com/v1/models": {"data": [{"id": "claude-sonnet-4-5"}]}},
    )
    assert anthropic_models("k") == ["claude-sonnet-4-5"]


def test_scan_without_keys_is_graceful(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("prebuttal.providers.ollama.ollama_models", lambda base: [])
    listings = {x.backend: x for x in scan()}
    assert listings["api-gemini"].note.startswith("(no key")
    assert listings["ollama"].note == "(not running)"
    assert listings["agent-claude"].models == ["opus", "sonnet", "haiku"]
    assert listings["agent-codex"].note.startswith("the codex CLI picks")


def test_render_marks_default_and_shows_toml_hint():
    text = render(
        [ModelListing("api-gemini", ["gemini-2.5-flash", "gemini-2.5-pro"], "gemini-2.5-flash")]
    )
    assert "api-gemini" in text
    assert "- gemini-2.5-flash *" in text
    assert "- gemini-2.5-pro" in text
    assert "prebuttal.toml" in text and "--model" in text


def test_cli_models_command(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("prebuttal.providers.ollama.ollama_models", lambda base: [])
    rc = cli.main(["models"])
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    for backend in ("api-gemini", "api-openai", "api-anthropic", "ollama", "agent-claude", "relay"):
        assert backend in out
