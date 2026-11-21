"""Ollama backend: local models — zero cost, papers never leave the machine.

Except Ollama Cloud models (``gpt-oss:120b-cloud``): listed and called like
local ones, but run on ollama.com.  Never picked by default; named, they are
announced before any call."""

from __future__ import annotations

import os
import re
import sys

import httpx

from ..models import Usage
from .base import BaseProvider, ProviderError, TransientProviderError


def ollama_base_url() -> str:
    """The Ollama URL to call. ``OLLAMA_HOST`` is often the *server's* bind
    address as Ollama documents it (``0.0.0.0:11434``, no scheme): a client
    reaches that on loopback, over http.  ``localhost`` and ``0.0.0.0`` are
    normalised here once, so listings, errors and requests all agree."""
    host = (
        (
            os.environ.get("PREBUTTAL_OLLAMA_HOST")
            or os.environ.get("OLLAMA_HOST")
            or "http://localhost:11434"
        )
        .strip()
        .rstrip("/")
    )
    if "://" not in host:
        host = "http://" + host
    scheme, rest = host.split("://", 1)
    if scheme == "http" and ":" not in rest.split("/", 1)[0]:  # like Ollama: port 11434
        rest = rest.replace("/", ":11434/", 1) if "/" in rest else rest + ":11434"
    return f"{scheme}://{rest}".replace("://0.0.0.0", "://127.0.0.1").replace(
        "://localhost:", "://127.0.0.1:"
    )


def ollama_tags(base: str) -> list[dict]:
    """Installed models as /api/tags lists them; [] when Ollama isn't reachable."""
    try:
        r = httpx.get(f"{base}/api/tags", timeout=2.5)
        r.raise_for_status()
        return [m for m in r.json().get("models", []) if isinstance(m, dict) and m.get("name")]
    except Exception:
        return []


def is_cloud_model(name: str, tag: dict | None = None) -> bool:
    """An Ollama Cloud model: the local server forwards it to ollama.com.
    /api/tags marks one with ``remote_host``; its name ends in ``-cloud``."""
    if tag and (tag.get("remote_host") or tag.get("remote_model")):
        return True
    return name.lower().endswith(("-cloud", ":cloud"))


def _looks_like_embedding(tag: dict) -> bool:
    """An embedding model (nomic-embed-text, mxbai-embed-large, bge-m3,
    all-minilm) can't write a review; /api/tags only gives name and family."""
    details = tag.get("details") or {}
    families = [details.get("family") or "", *(details.get("families") or [])]
    return "embed" in tag["name"].lower() or any("bert" in str(f).lower() for f in families)


def _can_chat(base: str, name: str) -> bool:
    """What /api/show says, on Ollama versions that list capabilities."""
    try:
        r = httpx.post(f"{base}/api/show", json={"model": name}, timeout=2.5)
        caps = r.json().get("capabilities") if r.status_code == 200 else None
    except Exception:
        return True
    return not isinstance(caps, list) or "completion" in caps


_CTX_FLOOR = 8192  # never below what a short paper needs
_TEMPLATE_TOKENS = 64  # the chat template's role markers
_CUT_SLACK = 8  # a prompt this close to the context is one Ollama cut to fit
# what a BPE tokenizer (Llama 3's) splits text into, at most: digits in runs
# of up to three, letters in short pieces, every other symbol on its own; a
# space before a digit and a line break are tokens of their own too (a space
# before a word or a symbol joins it)
_PIECES = re.compile(r"\d+|[A-Za-z]+|\n+|[^\S\n]+(?=\d)|\S")


def upper_tokens(text: str) -> int:
    """At least as many tokens as ``text`` takes (a dense table runs near two
    characters a token, where English prose is near four): a context sized
    from it holds the prompt, at some memory spent on margin."""
    n = 0
    for m in _PIECES.finditer(text):
        s = m.group(0)
        n += -(-len(s) // 3) if s[0].isascii() and s[0].isalnum() else 1
    return n


def _int(v: object) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


_CTX_STEP = 2048  # sizes in steps, so reviewers of one paper share a loaded model


def _model_context(base: str, name: str) -> int:
    """The longest context ``name`` was trained for (``*.context_length`` in
    /api/show's model_info); 0 when Ollama does not say."""
    try:
        r = httpx.post(f"{base}/api/show", json={"model": name}, timeout=5)
        info = r.json().get("model_info") if r.status_code == 200 else None
    except Exception:
        return 0
    if not isinstance(info, dict):
        return 0
    sizes = [
        v
        for k, v in info.items()
        if str(k).endswith(".context_length") and isinstance(v, int) and v > 0
    ]
    return max(sizes, default=0)


def pick_ollama_model(base_url: str | None = None, tags: list[dict] | None = None) -> str:
    """The installed model a review runs on when none is configured: the first
    local one in Ollama's list that can chat (never a cloud model: ``ollama``
    means the paper stays here), "" when there is none. Pass ``tags`` from
    an earlier ollama_tags() to skip a second listing."""
    base = base_url or ollama_base_url()
    tags = ollama_tags(base) if tags is None else tags
    candidates = [
        t["name"] for t in tags if not _looks_like_embedding(t) and not is_cloud_model(t["name"], t)
    ]
    return next((name for name in candidates[:6] if _can_chat(base, name)), "")


class OllamaProvider(BaseProvider):
    kind = "ollama"

    def __init__(self, backend: str = "ollama", model: str = "", **kw):
        base = ollama_base_url()
        if not model:
            tags = ollama_tags(base)
            model = pick_ollama_model(base, tags)
            if not model:
                cloud = [t["name"] for t in tags if is_cloud_model(t["name"], t)]
                raise ProviderError(
                    f"no local Ollama chat model at {base} — start it (`ollama serve`) "
                    "and pull one (`ollama pull llama3.1`); embedding models can't review"
                    + (
                        f"; {', '.join(cloud[:3])} run on Ollama Cloud and are used only "
                        "when named (`--model`)"
                        if cloud
                        else ""
                    )
                )
        elif is_cloud_model(model):
            print(
                f"[prebuttal] ollama model {model} runs on Ollama Cloud (ollama.com): "
                "the paper leaves this machine",
                file=sys.stderr,
            )
        super().__init__(backend, model, **kw)
        self.base_url = base

    _max_ctx: int | None = None  # the model's trained context, asked once

    def _num_ctx(self, system: str, user: str, max_tokens: int) -> int:
        """A context the whole prompt and the answer fit in, up to the model's
        own.  Ollama's default is as small as 4K tokens and it cuts a longer
        prompt without saying so: a reviewer would rate half a paper.

        Only a prompt that by itself surely does not fit (a usual count, ~4
        characters a token) fails here, before any call.  The rest is sent:
        a prompt that did not fit after all is caught on the way back (the
        server refusing to truncate, or a prompt filling the context), and
        an answer that ran out of room is cut JSON, a failed review — how
        long a review runs is the model's, not ours to guess."""
        from ..pack import estimate_tokens

        prompt = upper_tokens(system) + upper_tokens(user) + _TEMPLATE_TOKENS
        if self._max_ctx is None:
            self._max_ctx = _model_context(self.base_url, self.model)
        likely = estimate_tokens(len(system) + len(user)) + _TEMPLATE_TOKENS
        if self._max_ctx and likely > self._max_ctx - _CUT_SLACK:
            raise ProviderError(
                f"this prompt takes ~{likely:,} tokens and {self.model} holds "
                f"{self._max_ctx:,}: the paper does not fit — use a model with a longer "
                "context, or another backend"
            )
        size = max(_CTX_FLOOR, -(-(prompt + max_tokens) // _CTX_STEP) * _CTX_STEP)
        return min(size, self._max_ctx) if self._max_ctx else size

    def _complete(self, *, system, user, temperature, seed, max_tokens):
        num_ctx = self._num_ctx(system, user, max_tokens)
        options = {"temperature": temperature, "num_predict": max_tokens, "num_ctx": num_ctx}
        if seed is not None:
            options["seed"] = seed
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": options,
            # an error, not a cut prompt, when it does not fit (Ollama versions
            # that know these fields; older ones ignore them)
            "truncate": False,
            "shift": False,
        }
        if self.applied_effort:  # gpt-oss takes "low" | "medium" | "high"
            payload["think"] = self.applied_effort
        try:
            r = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout_s)
        except httpx.HTTPError as e:
            raise TransientProviderError(f"cannot reach Ollama at {self.base_url}: {e}") from e
        if r.status_code >= 400 and "context" in r.text.lower():  # the prompt did not fit
            raise ProviderError(
                f"the prompt does not fit {self.model}'s context ({num_ctx:,} tokens asked): "
                f"{r.text[:200]}"
            )
        if r.status_code >= 500:  # e.g. the model is still loading or ran out of memory
            raise TransientProviderError(f"Ollama HTTP {r.status_code}: {r.text[:300]}")
        if r.status_code != 200:
            raise ProviderError(f"Ollama HTTP {r.status_code}: {r.text[:300]}")
        try:
            data = r.json()
        except ValueError as e:
            raise ProviderError(f"non-JSON Ollama response: {r.text[:200]}") from e
        if not isinstance(data, dict) or not isinstance(data.get("message") or {}, dict):
            raise ProviderError(f"unexpected Ollama response shape: {r.text[:200]}")
        text = (data.get("message") or {}).get("content", "")
        evaluated = _int(data.get("prompt_eval_count"))
        # the whole prompt: evaluated now plus taken from the cache (newer Ollama)
        prompt = evaluated + _int(data.get("prompt_eval_cached_count"))
        # A cut prompt fills the context to the brim; one that fits leaves room
        # (a long answer that runs short of room only ends early, the prompt whole)
        if prompt >= num_ctx - _CUT_SLACK:
            raise ProviderError(
                f"Ollama read {prompt:,} prompt tokens into a {num_ctx:,}-token context — "
                "the paper may have been cut; not used"
            )
        return text, Usage(evaluated, _int(data.get("eval_count")))
