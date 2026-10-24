"""Prebuttal CLI.

Commands:
  prebuttal run <paper>   review a PDF / LaTeX project / arXiv link
  prebuttal backends      show detected backends
  prebuttal init          write a sample prebuttal.toml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from . import keys as key_store
from .config import (
    CONFIG_FILENAME,
    DEFAULT_CONFIG_TOML,
    ConfigError,
    apply_overrides,
    load_config,
)
from .dryrun import render_dry_run
from .ingestion import IngestError, ingest
from .orchestrator import run_report
from .pack import render_pack
from .providers import (
    NoBackendError,
    ProviderError,
    auto_candidates,
    build_provider,
    resolve_backends,
    scan_backends,
)
from .report import dumps_json, render_markdown
from .runs import find_run, load_history, render_diff, render_runs_table, save_run
from .share import render_share_html
from .venues import VENUE_KEYS, get_venue

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NO_BACKEND = 3
EXIT_PARTIAL = 4
EXIT_ALL_FAILED = 5


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prebuttal",
        description="Pre-submission review stress test: three independent AI reviewers "
        "plus an area chair, real conference review forms.",
    )
    parser.add_argument("--version", action="version", version=f"prebuttal {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="review a paper (PDF / LaTeX dir / arXiv link)")
    run.add_argument("paper", help="path to .pdf, LaTeX project dir, or arXiv link/id")
    run.add_argument("--venue", choices=VENUE_KEYS, help="review form to use")
    run.add_argument("-c", "--config", default=None, help="prebuttal.toml path")
    run.add_argument("--reviewers", type=int, default=None, help="number of reviewers (1-5)")
    run.add_argument("--backend", default=None, help="force a backend for all roles")
    run.add_argument("--model", default=None, help="force a model id for all roles")
    run.add_argument("--seed", type=int, default=None, help="reproducibility seed")
    run.add_argument("--dry-run", action="store_true", help="show cost + backends, call nothing")
    run.add_argument(
        "--json", metavar="PATH", default=None, help="also write machine-readable JSON"
    )
    run.add_argument("--share", action="store_true", help="also write a shareable HTML page")
    run.add_argument("--out", default="prebuttal-report.md", help="markdown output path")
    run.add_argument("--stdout", action="store_true", help="print the full report to stdout")
    run.add_argument(
        "--no-save",
        action="store_true",
        help="do not archive this run to the run history (~/.prebuttal)",
    )

    sub.add_parser("backends", help="list detected review backends")

    init = sub.add_parser("init", help="write a sample prebuttal.toml")
    init.add_argument("--force", action="store_true", help="overwrite existing file")

    runs_p = sub.add_parser("runs", help="list archived review runs")
    runs_p.add_argument("--paper", default=None, help="filter by paper title or id substring")
    runs_p.add_argument("-n", "--limit", type=int, default=15, help="show the N most recent runs")
    runs_p.add_argument("--json", action="store_true", help="machine-readable history")

    show_p = sub.add_parser("show", help="re-display an archived run (id prefix is enough)")
    show_p.add_argument("run_id")
    show_p.add_argument("--json", action="store_true", help="print the stored report.json")

    diff_p = sub.add_parser(
        "diff", help="compare two archived runs of a paper (ratings + weakness movement)"
    )
    diff_p.add_argument("run_a")
    diff_p.add_argument("run_b")

    key_p = sub.add_parser("key", help="store API keys for quick setup")
    key_sub = key_p.add_subparsers(dest="key_cmd", required=True)
    key_set = key_sub.add_parser("set", help="store a key (prompted, hidden input)")
    key_set.add_argument("backend", help="gemini | openai | anthropic (or the env var name)")
    key_set.add_argument("--key", default=None, help="non-interactive: pass the key directly")
    key_sub.add_parser("status", help="show which keys are set (masked)")
    key_unset = key_sub.add_parser("unset", help="remove a stored key")
    key_unset.add_argument("backend", help="gemini | openai | anthropic (or the env var name)")

    return parser


# ------------------------------------------------------------------ commands


def cmd_backends(args) -> int:
    statuses = scan_backends(None)
    print("Detected review backends:")
    for s in statuses:
        print("  " + s.line())
    avail = auto_candidates(statuses, None)
    if avail:
        print(f"\nAuto mode will draw from: {', '.join(s.backend for s in avail)}")
        return EXIT_OK
    print("\nNo automatic backend available. Install one of:")
    print("  npm i -g @anthropic-ai/claude-code   -> agent-claude (subscription)")
    print("  npm i -g @openai/codex               -> agent-codex (subscription)")
    print("  set GEMINI_API_KEY                   -> api-gemini (free tier)")
    print("  set OPENAI_API_KEY / ANTHROPIC_API_KEY")
    print("  ollama pull llama3.1 && ollama serve -> ollama (local, private)")
    print("Or answer the reviews yourself / via your agent: prebuttal run ... --backend relay")
    return EXIT_NO_BACKEND


def cmd_init(args) -> int:
    path = Path(CONFIG_FILENAME)
    if path.exists() and not args.force:
        print(f"{path} already exists (use --force to overwrite)", file=sys.stderr)
        return EXIT_USAGE
    path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")
    print(f"wrote {path} — edit repo_url and backends to taste")
    return EXIT_OK


def cmd_runs(args) -> int:
    records = load_history()
    if args.paper:
        q = args.paper.lower()
        records = [
            r
            for r in records
            if q in r.id.lower() or q in r.paper_title.lower() or q in r.source.lower()
        ]
    records = records[: max(1, args.limit)]
    if args.json:
        import json as jsonlib

        print(jsonlib.dumps([r.__dict__ for r in records], indent=2, ensure_ascii=False))
        return EXIT_OK
    print(render_runs_table(records))
    return EXIT_OK


def _resolve_run_or_exit(query: str):
    match, candidates = find_run(query)
    if match is None:
        print(f"error: no unique run matches '{query}'", file=sys.stderr)
        if candidates:
            print("candidates:", file=sys.stderr)
            print(render_runs_table(candidates), file=sys.stderr)
        return None
    return match


def cmd_show(args) -> int:
    rec = _resolve_run_or_exit(args.run_id)
    if rec is None:
        return EXIT_USAGE
    if args.json:
        print((Path(rec.dir) / "report.json").read_text(encoding="utf-8"))
    else:
        print((Path(rec.dir) / "report.md").read_text(encoding="utf-8"))
    return EXIT_OK


def cmd_diff(args) -> int:
    a = _resolve_run_or_exit(args.run_a)
    if a is None:
        return EXIT_USAGE
    b = _resolve_run_or_exit(args.run_b)
    if b is None:
        return EXIT_USAGE
    try:
        print(render_diff(a, b))
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USAGE
    return EXIT_OK


def cmd_key(args) -> int:
    import getpass

    if args.key_cmd == "status":
        print("API key status (env vars take precedence over stored keys):")
        for name, var in key_store.KEY_MAP.items():
            masked = key_store.mask(var)
            src = key_store.source(var)
            print(f"  {name:<10} {masked or 'not set':<14} {f'[{src}]' if src else ''}")
        if all(key_store.mask(var) is None for var in key_store.KEY_MAP.values()):
            print(
                "\n  Quick start:  prebuttal key set gemini"
                "   (free key: aistudio.google.com/apikey)"
            )
        return EXIT_OK

    try:
        var = key_store.resolve_name(args.backend)
    except key_store.KeyError_ as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USAGE

    if args.key_cmd == "set":
        value = args.key or getpass.getpass(f"Paste your {args.backend} API key (input hidden): ")
        try:
            key_store.store_key(var, value)
        except key_store.KeyError_ as e:
            print(f"error: {e}", file=sys.stderr)
            return EXIT_USAGE
        print(f"stored {var} in {key_store.keys_path()}")
        print("Real environment variables still take precedence over stored keys.")
        print("Next: `prebuttal backends` should now show the backend as available.")
        return EXIT_OK

    # unset
    removed = key_store.unset_key(var)
    if removed:
        print(f"removed {var} from {key_store.keys_path()}")
    else:
        print(f"no stored {var} found")
    return EXIT_OK


def cmd_run(args) -> int:
    cfg = load_config(args.config)
    cfg = apply_overrides(
        cfg,
        venue=args.venue,
        seed=args.seed,
        backend=args.backend,
        model=args.model,
        reviewers_count=args.reviewers,
    )
    venue = get_venue(cfg.venue)

    _log(f"[prebuttal] ingesting {args.paper} ...")
    try:
        paper = ingest(args.paper)
    except IngestError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USAGE
    _log(
        f"[prebuttal] parsed: “{paper.title}” — "
        f"{len(paper.sections)} sections, {len(paper.tables)} tables, "
        f"{len(paper.figures)} figure captions"
    )
    for w in paper.warnings:
        _log(f"[prebuttal] warning: {w}")

    statuses = scan_backends(cfg)
    try:
        resolved, ac = resolve_backends(cfg, statuses)
    except NoBackendError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_NO_BACKEND

    pack = render_pack(paper, budget_chars=cfg.budget_chars)

    if args.dry_run:
        print(render_dry_run(cfg, resolved, ac, len(pack), statuses))
        return EXIT_OK

    providers = {}
    try:
        for rid, backend, model in resolved:
            providers[rid] = build_provider(backend, model, cfg)
        ac_provider = build_provider(ac[0], ac[1], cfg)
    except ProviderError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_NO_BACKEND

    if any(b == "relay" for (_r, b, _m) in resolved) or ac[0] == "relay":
        _log(
            f"[prebuttal] relay mode: review requests are spooled to '{cfg.relay_dir}/' — "
            f"answer each <stem>.req.md by writing JSON to <stem>.ans.md "
            f"(protocol: {cfg.relay_dir}/README.txt; "
            f"waiting up to {cfg.relay_timeout_s}s per call). "
            "For automatic reviews instead, install claude/codex CLI or set GEMINI_API_KEY."
        )

    report = run_report(paper, cfg, venue, providers, ac_provider, log=_log)

    md = render_markdown(report, venue)
    out_path = Path(args.out)
    out_path.write_text(md, encoding="utf-8")

    json_path = None
    json_str = dumps_json(report, venue)
    if args.json:
        json_path = Path(args.json)
        json_path.write_text(json_str, encoding="utf-8")

    share_path = None
    html_str = render_share_html(report, venue, cfg.repo_url) if args.share else None
    if html_str:
        share_path = out_path.with_suffix(".html")
        share_path.write_text(html_str, encoding="utf-8")

    # Advanced feature, zero footprint on basic usage: archive best-effort,
    # and a failure to archive must never fail the review run itself.
    if not args.no_save:
        try:
            rec = save_run(report, venue, cfg, md=md, json_str=json_str, html=html_str)
            print(f"Saved:    {rec.id}  (`prebuttal show {rec.id}`)")
        except OSError as e:
            _log(f"[prebuttal] warning: could not archive this run ({e})")

    agg = report.aggregate
    if agg.mean is not None:
        print(
            f"\nPredicted: {agg.mean:g}/{venue.rating_field.max:g} "
            f"(σ {agg.std:g}, range {agg.min:g}–{agg.max:g})"  # noqa: RUF001
        )
    else:
        print("\nPredicted: n/a (no parseable ratings)")
    print(f"Report:   {out_path}")
    if json_path:
        print(f"JSON:     {json_path}")
    if share_path:
        print(f"Share:    {share_path}")
    if args.stdout:
        print()
        print(md)

    failed = [r for r in report.reviews if not r.parse_ok]
    if len(failed) == len(report.reviews):
        return EXIT_ALL_FAILED
    if failed or not report.meta.parse_ok:
        return EXIT_PARTIAL
    return EXIT_OK


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        applied = key_store.apply_stored_keys()  # zero-friction: stored keys → env
        if applied and args.cmd != "key":
            _log("[prebuttal] using stored keys: " + ", ".join(applied))
        if args.cmd == "init":
            return cmd_init(args)
        if args.cmd == "backends":
            return cmd_backends(args)
        if args.cmd == "runs":
            return cmd_runs(args)
        if args.cmd == "show":
            return cmd_show(args)
        if args.cmd == "diff":
            return cmd_diff(args)
        if args.cmd == "key":
            return cmd_key(args)
        return cmd_run(args)
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
