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
    # scan() hits OpenRouter's public catalog — keep the test offline
    monkeypatch.setattr(
        "prebuttal.modelscan.openrouter_catalog",
        lambda max_rows=40: (["some/model:free"], {"some/model:free": "(free)"}),
    )
    listings = {x.backend: x for x in scan()}
    assert listings["api-gemini"].note.startswith("(no key")
    assert listings["ollama"].note == "(not running)"
    assert listings["agent-claude"].models == ["opus", "sonnet", "haiku"]
    assert listings["agent-codex"].note.startswith("the codex CLI picks")
    orl = listings["api-openrouter"]
    assert orl.models == ["some/model:free"] and orl.prices["some/model:free"] == "(free)"


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
    monkeypatch.setattr("prebuttal.modelscan.openrouter_catalog", lambda max_rows=40: None)
    rc = cli.main(["models"])
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    for backend in (
        "api-gemini",
        "api-openai",
        "api-anthropic",
        "api-openrouter",
        "ollama",
        "agent-claude",
        "relay",
    ):
        assert backend in out


def test_openrouter_catalog_filters_and_prices(monkeypatch):
    import prebuttal.modelscan as ms

    payload = {
        "data": [
            {  # free text model — listed with (free)
                "id": "acme/tiny:free",
                "architecture": {"output_modalities": ["text"]},
                "pricing": {"prompt": "0", "completion": "0"},
            },
            {  # notable paid model — listed with per-1M price
                "id": "acme/llama-big",
                "architecture": {"output_modalities": ["text"]},
                "pricing": {"prompt": "0.0000015", "completion": "0.000006"},
            },
            {  # image-only — dropped
                "id": "acme/imagen-ish",
                "architecture": {"output_modalities": ["image"]},
                "pricing": {"prompt": "0.0001", "completion": "0"},
            },
            {  # music model — dropped by noise filter
                "id": "google/lyria-3-clip",
                "architecture": {"output_modalities": ["text", "audio"]},
                "pricing": {"prompt": "0", "completion": "0"},
            },
            {  # non-notable paid — kept out (not free, no notable family)
                "id": "acme/other-model",
                "architecture": {"output_modalities": ["text"]},
                "pricing": {"prompt": "0.000002", "completion": "0.000004"},
            },
        ]
    }
    monkeypatch.setattr(ms, "_get", lambda url, headers=None: payload)
    result = ms.openrouter_catalog()
    assert result is not None
    ids, prices = result
    assert ids == ["acme/tiny:free", "acme/llama-big"]  # free ids first
    assert prices["acme/tiny:free"] == "(free)"
    assert prices["acme/llama-big"] == "($1.50/$6.00 per 1M)"
    assert all("imagen" not in i and "lyria" not in i and "other-model" not in i for i in ids)
