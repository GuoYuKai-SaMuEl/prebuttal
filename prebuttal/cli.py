"""Prebuttal CLI.

Commands:
  prebuttal run <paper>       review a PDF / LaTeX project / arXiv link
  prebuttal retry [run]       re-run only the reviewers that failed, then the AC
  prebuttal check <paper>     desk-reject pre-flight (anonymity, page limit, ??) — no model
  prebuttal projects          list papers (one project per paper, runs grouped)
  prebuttal runs [project]    list runs; show / open / diff / note / rm / export them
  prebuttal dashboard         local HTML overview of every project and run
  prebuttal backends [name]   what you can review with (auth, models)
  prebuttal init              write a sample prebuttal.toml

Runs are referenced as ``latest`` (default), ``<project>`` (its newest run),
``<project>#3`` (run 3), ``<project>~1`` (one before the newest) or by id prefix.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

from . import __version__
from . import keys as key_store
from .config import (
    BACKEND_ENV,
    CONFIG_FILENAME,
    DEFAULT_CONFIG_TOML,
    ConfigError,
    apply_overrides,
    env_backend,
    load_config,
    role_effort,
)
from .dashboard import dashboard_path, ensure_html, render_dashboard
from .dryrun import render_dry_run
from .ingestion import IngestError, ingest
from .models import EFFORT_LEVELS, dataclass_to_dict
from .orchestrator import RunInterrupted, run_report
from .outputs import FORMATS, parse_formats, write_local
from .pack import render_pack
from .projects import (
    ProjectError,
    assign_project,
    forget_project,
    load_projects,
    normalize_key,
    rename_project,
    slugify,
)
from .providers import (
    RELAY_AGENT_HINT,
    NoBackendError,
    ProviderError,
    auto_candidates,
    build_provider,
    detect_host_agent,
    resolve_backends,
    scan_backends,
)
from .report import dumps_json, render_markdown, render_plan, report_from_dict
from .runs import (
    delete_runs,
    load_history,
    make_private_dir,
    previous_run,
    project_summaries,
    rename_in_history,
    render_diff,
    render_projects_table,
    render_runs_table,
    resolve_ref,
    save_run,
    set_note,
)
from .share import render_share_html
from .venues import VENUE_KEYS, VENUES, VenueError, get_venue

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NO_BACKEND = 3
EXIT_PARTIAL = 4
EXIT_ALL_FAILED = 5
EXIT_CHECK_FAILED = 6  # `check` found something that can get the paper desk-rejected


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prebuttal",
        description="Pre-submission review stress test: three independent AI reviewers "
        "plus an area chair, real conference review forms.",
    )
    parser.add_argument("--version", action="version", version=f"prebuttal {__version__}")
    # commands added without help= stay out of the listing (hidden aliases)
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="<command>")

    # no abbreviations: `--out x` must not silently mean `--out-dir x`
    run = sub.add_parser(
        "run", help="review a paper (PDF / LaTeX dir / arXiv link)", allow_abbrev=False
    )
    run.add_argument("paper", help="path to .pdf, LaTeX project dir, or arXiv link/id")
    run.add_argument(
        "--venue",
        default=None,
        help=f"review form: {', '.join(VENUE_KEYS)}, a custom venue name, "
        "or a venue .toml file (see `prebuttal venues`)",
    )
    run.add_argument("-c", "--config", default=None, help="prebuttal.toml path")
    run.add_argument("--reviewers", type=int, default=None, help="number of reviewers (1-5)")
    run.add_argument("--backend", default=None, help="force a backend for all roles")
    run.add_argument("--model", default=None, help="force a model id for all roles")
    run.add_argument("--seed", type=int, default=None, help="reproducibility seed")
    run.add_argument(
        "--effort",
        choices=EFFORT_LEVELS,
        default=None,
        help="reasoning effort for thinking models (default: each model's own)",
    )
    run.add_argument(
        "--figures",
        action="store_true",
        help="also show figures as images to reviewers on vision-capable API backends",
    )
    run.add_argument("--dry-run", action="store_true", help="show cost + backends, call nothing")
    run.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="skip the plan confirmation prompt (auto mode; non-interactive never prompts)",
    )
    run.add_argument(
        "--project",
        default=None,
        help="project name (default: one per paper, found from its path / arXiv id)",
    )
    run.add_argument(
        "--note", default="", help='what changed in this revision, e.g. "added ablation"'
    )
    run.add_argument(
        "--format",
        default=None,
        help="report formats to write: md,html,json (default md,html; see [output])",
    )
    run.add_argument(
        "--out-dir",
        default=None,
        help="reports folder (default ./prebuttal-reports; one subfolder per run)",
    )
    run.add_argument(
        "--json", metavar="PATH", default=None, help="also write machine-readable JSON here"
    )
    run.add_argument("--stdout", action="store_true", help="print the full report to stdout")
    run.add_argument(
        "--no-save",
        action="store_true",
        help="do not archive this run to the run history (~/.prebuttal)",
    )

    retry_p = sub.add_parser(
        "retry",
        help="re-run only the failed reviewers of a run, then the AC (default: latest)",
        allow_abbrev=False,
    )
    retry_p.add_argument("run", nargs="?", default=None, help="run reference (default: latest)")

    check_p = sub.add_parser(
        "check",
        help="desk-reject pre-flight: anonymity, page limit, required sections, ?? — no model",
    )
    check_p.add_argument("paper", help="path to .pdf, LaTeX project dir, or arXiv link/id")
    check_p.add_argument(
        "--venue", default=None, help="whose rules to check against (as for `run`; default neurips)"
    )

    backends_p = sub.add_parser(
        "backends", help="what you can review with: backends, their auth and default models"
    )
    backends_p.add_argument(
        "backend", nargs="?", default=None, help="list this backend's models instead"
    )

    init = sub.add_parser("init", help="write a sample prebuttal.toml")
    init.add_argument("--force", action="store_true", help="overwrite existing file")

    proj_p = sub.add_parser("projects", help="list projects (one per paper)")
    proj_sub = proj_p.add_subparsers(dest="proj_cmd")
    proj_sub.add_parser("list", help="list projects (default)")
    ren = proj_sub.add_parser("rename", help="rename a project")
    ren.add_argument("old")
    ren.add_argument("new")
    prm = proj_sub.add_parser("rm", help="delete a project and all its archived runs")
    prm.add_argument("name")
    prm.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")
    proj_p.add_argument("--json", action="store_true", help="machine-readable list")

    runs_p = sub.add_parser("runs", help="list archived review runs")
    runs_p.add_argument("project", nargs="?", default=None, help="only this project's runs")
    runs_p.add_argument("--paper", default=None, help="filter by paper title or id substring")
    runs_p.add_argument("-n", "--limit", type=int, default=20, help="show the N most recent runs")
    runs_p.add_argument("--json", action="store_true", help="machine-readable history")

    show_p = sub.add_parser("show", help="print an archived report (default: latest)")
    show_p.add_argument("run", nargs="?", default=None, help="run reference (default: latest)")
    show_p.add_argument("--json", action="store_true", help="print the stored report.json")

    plan_p = sub.add_parser(
        "plan", help="print a run's revision plan as a checklist (default: latest)"
    )
    plan_p.add_argument("run", nargs="?", default=None, help="run reference (default: latest)")
    plan_p.add_argument("--json", action="store_true", help="machine-readable action items")

    open_p = sub.add_parser("open", help="open a run's HTML report in the browser")
    open_p.add_argument("run", nargs="?", default=None, help="run reference (default: latest)")
    open_p.add_argument("--md", action="store_true", help="open the Markdown file instead")

    diff_p = sub.add_parser(
        "diff",
        help="compare two runs (default: latest vs the run before it, same project)",
    )
    diff_p.add_argument("run_a", nargs="?", default=None)
    diff_p.add_argument("run_b", nargs="?", default=None)
    diff_p.add_argument(
        "--llm",
        action="store_true",
        help="match revision-plan items by meaning with one call to the AC's backend",
    )

    note_p = sub.add_parser("note", help="attach a note to a run (shown in lists and dashboard)")
    note_p.add_argument("run", help="run reference")
    note_p.add_argument("text", help='e.g. "after adding the Perceiver baseline"')

    rm_p = sub.add_parser("rm", help="delete archived runs")
    rm_p.add_argument("runs", nargs="+", help="run references")
    rm_p.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")

    exp_p = sub.add_parser("export", help="copy a run's report out of the archive")
    exp_p.add_argument("run", nargs="?", default=None, help="run reference (default: latest)")
    exp_p.add_argument(
        "-f",
        "--format",
        default=None,
        choices=["md", "html", "json"],
        help="report format (default: the -o file's extension, else html)",
    )
    exp_p.add_argument(
        "-o", "--output", default=None, help="file path (default: ./<project>-<n>.<ext>)"
    )

    dash_p = sub.add_parser("dashboard", help="write and open a local HTML overview of all runs")
    dash_p.add_argument("--no-open", action="store_true", help="write the file, don't open it")

    key_p = sub.add_parser("key", help="store or remove an API key (status: prebuttal backends)")
    key_sub = key_p.add_subparsers(dest="key_cmd", required=True, metavar="{set,unset}")
    key_set = key_sub.add_parser("set", help="store a key (prompted, hidden input)")
    key_set.add_argument("backend", help="gemini | openai | anthropic (or the env var name)")
    key_set.add_argument("--key", default=None, help="non-interactive: pass the key directly")
    key_sub.add_parser("status")  # hidden 0.4 alias: `prebuttal backends` shows key status
    key_unset = key_sub.add_parser("unset", help="remove a stored key")
    key_unset.add_argument("backend", help="gemini | openai | anthropic (or the env var name)")

    sub.add_parser("models")  # hidden 0.4 alias of `backends <name>`

    ven_p = sub.add_parser("venues", help="list review forms; add your own venue")
    ven_sub = ven_p.add_subparsers(dest="venues_cmd")
    ven_new = ven_sub.add_parser("new", help="write a venue template to edit")
    ven_new.add_argument("key", help="short name, e.g. cvpr or lab-review")
    ven_new.add_argument(
        "--from", dest="base", default=None, choices=VENUE_KEYS, help="start from a built-in venue"
    )
    ven_new.add_argument(
        "--here",
        action="store_true",
        help="write to ./.prebuttal/venues (shared with the project) instead of ~/.prebuttal",
    )
    ven_show = ven_sub.add_parser("show", help="print a venue's scores and review form")
    ven_show.add_argument("venue", help="venue name or .toml path")

    return parser


# ------------------------------------------------------------------ commands


_API_KEYS = {
    "api-gemini": "GEMINI_API_KEY",
    "api-openai": "OPENAI_API_KEY",
    "api-anthropic": "ANTHROPIC_API_KEY",
    "api-openrouter": "OPENROUTER_API_KEY",
}


def _auth(s) -> str:
    """Where a backend's access comes from, for the one setup view."""
    var = _API_KEYS.get(s.backend)
    if var:
        src = key_store.source(var)
        if not src:
            return s.detail  # "not set (where to get one; `prebuttal key set ...`)"
        where = "env var" if src == "env" else "stored key"
        return f"{where} {var} ({key_store.mask(var)})"
    if s.backend in ("agent-claude", "agent-codex"):
        return "CLI login (subscription)" if s.available else s.detail
    return s.detail


def cmd_backends(args) -> int:
    if args.backend:
        return _backend_models(args.backend)
    try:
        cfg = load_config(None)  # only to list its [agents.*]; nothing runs here
    except ConfigError:
        cfg = None
    statuses = scan_backends(cfg)
    print("Review backends ([x] = ready):")
    for s in statuses:
        mark = "x" if s.available else " "
        model = f"  · model {s.default_model}" if s.available and s.default_model else ""
        print(f"  [{mark}] {s.backend:<15} {_auth(s)}{model}")
    host_agent = detect_host_agent()
    if host_agent:
        print("\nHint: " + RELAY_AGENT_HINT.format(agent=host_agent))
    avail = auto_candidates(statuses, cfg)
    if avail:
        print(f"\nAuto mode draws from: {', '.join(s.backend for s in avail)}")
        print(
            "Models of one backend: prebuttal backends <name>  ·  "
            "keys: prebuttal key set|unset <name>"
        )
        return EXIT_OK
    print("\nNo automatic backend available. Install one of:")
    print("  npm i -g @anthropic-ai/claude-code   -> agent-claude (subscription)")
    print("  npm i -g @openai/codex               -> agent-codex (subscription)")
    print("  set GEMINI_API_KEY                   -> api-gemini (free tier)")
    print("  set OPENAI_API_KEY / ANTHROPIC_API_KEY")
    print("  ollama pull llama3.1 && ollama serve -> ollama (local, private)")
    print("Or answer the reviews yourself / via your agent: prebuttal run ... --backend relay")
    return EXIT_NO_BACKEND


def cmd_check(args) -> int:
    from .check import CheckError, check_source, render_check

    try:
        # only the venue is read from a found prebuttal.toml: nothing runs, nothing is sent
        venue = get_venue(args.venue or load_config(None).venue)
    except VenueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USAGE
    try:
        result = check_source(args.paper, venue)
    except CheckError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USAGE
    print(render_check(result, venue))
    return EXIT_CHECK_FAILED if result.errors else EXIT_OK


def _preflight(source: str, venue) -> list[str]:
    """`check`'s findings for `run`'s report; never fails the run.

    Only for the user's own draft (a local PDF or LaTeX project): an arXiv
    paper is already public and camera-ready, so its "problems" are noise."""
    from .check import check_source, preflight_warnings

    if not Path(source.strip()).exists():
        return []
    try:
        found = preflight_warnings(check_source(source, venue))
    except Exception as e:  # a pre-flight problem must not cost the review
        return [f"Pre-flight check skipped: {e}"]
    # hidden text is already reported (loudly) by ingestion
    return [w for w in found if "hidden from human readers" not in w]


def cmd_init(args) -> int:
    path = Path(CONFIG_FILENAME)
    if path.exists() and not args.force:
        print(f"{path} already exists (use --force to overwrite)", file=sys.stderr)
        return EXIT_USAGE
    path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")
    print(f"wrote {path} — edit reviewers and backends to taste")
    return EXIT_OK


def cmd_projects(args) -> int:
    action = args.proj_cmd or "list"
    if action == "rename":
        known = {p.key for p in project_summaries()} | set(load_projects())
        if args.old not in known:
            print(f"error: no project '{args.old}' — see `prebuttal projects`", file=sys.stderr)
            return EXIT_USAGE
        try:
            new = rename_project(args.old, args.new)
        except (ProjectError, OSError) as e:
            print(f"error: {e}", file=sys.stderr)
            return EXIT_USAGE
        n = rename_in_history(args.old, new)
        print(f"renamed {args.old} → {new} ({n} run{'s' if n != 1 else ''})")
        print("Existing report folders keep their old name; new runs use the new one.")
        return EXIT_OK
    if action == "rm":
        runs = [r for r in load_history() if r.project == args.name]
        if not runs and args.name not in load_projects():
            print(f"error: no project '{args.name}'", file=sys.stderr)
            return EXIT_USAGE
        what = f"project '{args.name}' and its {len(runs)} archived run(s)"
        if not _confirm(f"Delete {what}?", args.yes):
            return EXIT_USAGE
        delete_runs({r.id for r in runs})
        forget_project(args.name)
        print(f"deleted {what} (files under ./prebuttal-reports are left alone)")
        return EXIT_OK

    projects = project_summaries()
    if args.json:
        data = [
            {
                "project": p.key,
                "title": p.title,
                "runs": len(p.runs),
                "latest": p.latest.label,
                "latest_mean": p.latest.mean,
                "scale": p.latest.scale,
                "last_run": p.latest.ts,
            }
            for p in projects
        ]
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return EXIT_OK
    print(render_projects_table(projects))
    if projects:
        print("\nRuns of one project: prebuttal runs <project> · overview: prebuttal dashboard")
    return EXIT_OK


def cmd_runs(args) -> int:
    records = load_history()
    if args.project:
        records = [r for r in records if r.project == args.project]
        if not records:
            print(f"error: no runs in project '{args.project}'", file=sys.stderr)
            return EXIT_USAGE
    if args.paper:
        q = args.paper.lower()
        records = [
            r
            for r in records
            if q in r.id.lower() or q in r.paper_title.lower() or q in r.source.lower()
        ]
    records = records[: max(1, args.limit)]
    if args.json:
        print(json.dumps([r.__dict__ for r in records], indent=2, ensure_ascii=False))
        return EXIT_OK
    print(render_runs_table(records))
    return EXIT_OK


def _resolve_run_or_exit(query: str | None):
    match, candidates = resolve_ref(query)
    if match is None:
        if query is None and not candidates:
            print("error: no saved runs yet — `prebuttal run <paper>` first", file=sys.stderr)
            return None
        print(f"error: no unique run matches '{query}'", file=sys.stderr)
        if candidates:
            print("candidates:", file=sys.stderr)
            print(render_runs_table(candidates), file=sys.stderr)
        return None
    return match


def cmd_show(args) -> int:
    rec = _resolve_run_or_exit(args.run)
    if rec is None:
        return EXIT_USAGE
    name = "report.json" if args.json else "report.md"
    try:
        print((rec.dir_path / name).read_text(encoding="utf-8"))
    except OSError as e:
        print(f"error: archived {name} for {rec.label} is missing ({e})", file=sys.stderr)
        return EXIT_USAGE
    return EXIT_OK


def cmd_plan(args) -> int:
    rec = _resolve_run_or_exit(args.run)
    if rec is None:
        return EXIT_USAGE
    try:
        data = json.loads((rec.dir_path / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: archived report.json for {rec.label} is unreadable ({e})", file=sys.stderr)
        return EXIT_USAGE
    plan = report_from_dict(data).meta.action_plan
    if args.json:
        print(json.dumps([dataclass_to_dict(it) for it in plan], indent=2, ensure_ascii=False))
        return EXIT_OK
    if not plan:
        print(
            f"{rec.label} has no revision plan (runs before prebuttal 0.3, or the area chair "
            "failed). Re-run the paper to get one.",
            file=sys.stderr,
        )
        return EXIT_USAGE
    print(f"# Revision plan — {data.get('paper', {}).get('title', rec.label)} ({rec.label})")
    print()
    print("\n".join(render_plan(plan)))
    return EXIT_OK


def _open_in_browser(path: Path) -> None:
    import webbrowser

    opened = False
    with contextlib.suppress(Exception):
        opened = webbrowser.open(path.resolve().as_uri())
    if not opened:
        print("(could not open a browser here — open the file above yourself)")


def cmd_open(args) -> int:
    rec = _resolve_run_or_exit(args.run)
    if rec is None:
        return EXIT_USAGE
    try:
        path = rec.dir_path / "report.md" if args.md else ensure_html(rec)
    except (OSError, ValueError, KeyError) as e:
        print(f"error: cannot open {rec.label}: {e}", file=sys.stderr)
        return EXIT_USAGE
    print(f"{rec.label}: {path}")
    _open_in_browser(path)
    return EXIT_OK


def cmd_diff(args) -> int:
    if args.run_b is None:  # one or no ref: compare it with the run before it
        b = _resolve_run_or_exit(args.run_a)
        if b is None:
            return EXIT_USAGE
        a = previous_run(b)
        if a is None:
            print(
                f"error: {b.label} is the first run of '{b.project}' — nothing to compare yet. "
                "Revise the paper and run it again.",
                file=sys.stderr,
            )
            return EXIT_USAGE
    else:
        a = _resolve_run_or_exit(args.run_a)
        if a is None:
            return EXIT_USAGE
        b = _resolve_run_or_exit(args.run_b)
        if b is None:
            return EXIT_USAGE
    matcher = None
    if args.llm:
        matcher = _plan_matcher(args)
        if matcher is None:
            return EXIT_NO_BACKEND
    try:
        print(render_diff(a, b, match_plan=matcher))
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USAGE
    return EXIT_OK


def _plan_matcher(args):
    """`diff --llm`: the configured AC backend as a plan matcher."""
    from .diffmatch import match_plan

    cfg = apply_overrides(load_config(None), backend=env_backend())
    statuses = scan_backends(cfg)
    try:
        _resolved, ac = resolve_backends(cfg, statuses)
    except NoBackendError as e:
        print(f"error: {e}", file=sys.stderr)
        return None
    if ac[0] == "relay":
        print("error: --llm needs an automatic backend, not relay", file=sys.stderr)
        return None
    from .trust import pinned_by_file

    if not _config_trusted(cfg, [ac], pinned=pinned_by_file(None)):
        return None
    try:
        provider = build_provider(ac[0], ac[1], cfg, effort=role_effort(cfg, "AC"))
    except ProviderError as e:
        print(f"error: {e}", file=sys.stderr)
        return None
    _log(f"[prebuttal] matching revision plans via {provider.describe()}")
    return lambda a, bp, bw: match_plan(provider, a, bp, bw)


def cmd_note(args) -> int:
    rec = _resolve_run_or_exit(args.run)
    if rec is None:
        return EXIT_USAGE
    set_note(rec.id, args.text.strip())
    print(f"{rec.label}: note {'set' if args.text.strip() else 'cleared'}")
    return EXIT_OK


def _confirm(question: str, yes: bool) -> bool:
    if yes:
        return True
    if not _is_interactive():
        print(f"error: {question} — pass -y to confirm non-interactively", file=sys.stderr)
        return False
    try:
        ok = input(f"{question} [y/N]: ").strip().lower() in ("y", "yes")
    except EOFError:
        ok = False
    if not ok:
        _log("aborted")
    return ok


def cmd_rm(args) -> int:
    recs = []
    for ref in args.runs:
        rec = _resolve_run_or_exit(ref)
        if rec is None:
            return EXIT_USAGE
        recs.append(rec)
    labels = ", ".join(r.label for r in recs)
    if not _confirm(f"Delete {labels} from the archive?", args.yes):
        return EXIT_USAGE
    n = delete_runs({r.id for r in recs})
    print(f"deleted {n} run{'s' if n != 1 else ''}: {labels}")
    return EXIT_OK


def cmd_export(args) -> int:
    import shutil

    rec = _resolve_run_or_exit(args.run)
    if rec is None:
        return EXIT_USAGE
    # --format wins; without it, the -o extension picks (a .md path must not
    # receive HTML), and html is the fallback default.
    fmt = args.format
    if fmt is None:
        ext = Path(args.output or "").suffix.lstrip(".").lower()
        fmt = ext if ext in FORMATS else "html"
    try:
        src = ensure_html(rec) if fmt == "html" else rec.dir_path / f"report.{fmt}"
        dest = Path(args.output or f"{rec.project}-{rec.run_no}.{fmt}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    except (OSError, ValueError, KeyError) as e:
        print(f"error: cannot export {rec.label}: {e}", file=sys.stderr)
        return EXIT_USAGE
    print(f"{rec.label} → {dest}")
    return EXIT_OK


def cmd_dashboard(args) -> int:
    projects = project_summaries()
    for p in projects:  # older runs have no report.html yet
        for r in p.runs:
            with contextlib.suppress(OSError, ValueError, KeyError):
                ensure_html(r)
    path = dashboard_path()
    try:
        make_private_dir(path.parent)
        path.write_text(render_dashboard(projects), encoding="utf-8")
    except OSError as e:
        print(f"error: cannot write the dashboard: {e}", file=sys.stderr)
        return EXIT_USAGE
    print(f"Dashboard: {path}")
    if not args.no_open:
        _open_in_browser(path)
    return EXIT_OK


def _scale_summary(venue) -> str:
    rf = venue.rating_field
    step = ", half-steps" if rf.allow_float else ""
    return f"{rf.label} 1-{rf.max:g}{step}"


def cmd_venues(args) -> int:
    from .venues import custom

    if args.venues_cmd == "new":
        key = args.key.strip().lower()
        if not custom.KEY_RE.match(key):
            print("error: use a short lowercase name like 'cvpr' or 'lab-review'", file=sys.stderr)
            return EXIT_USAGE
        if key in VENUES:
            print(
                f"error: '{key}' is built in — pick another name "
                f"(e.g. `prebuttal venues new {key}-2027 --from {key}`)",
                file=sys.stderr,
            )
            return EXIT_USAGE
        folder = custom.search_dirs()[0] if args.here else custom.home_dir()
        toml_path, form_path = folder / f"{key}.toml", folder / f"{key}.md"
        if toml_path.exists() or form_path.exists():
            print(f"error: {toml_path} or {form_path} already exists", file=sys.stderr)
            return EXIT_USAGE
        toml_text, form_text = custom.render_template(key, VENUES[args.base] if args.base else None)
        folder.mkdir(parents=True, exist_ok=True)
        toml_path.write_text(toml_text, encoding="utf-8")
        form_path.write_text(form_text, encoding="utf-8")
        print(f"Wrote {toml_path}")
        print(f"      {form_path}")
        print("Edit the scores in the .toml and paste the venue's reviewer guidelines into")
        print(
            f"the .md, then: prebuttal venues show {key}  ·  prebuttal run paper.pdf --venue {key}"
        )
        return 0

    if args.venues_cmd == "show":
        try:
            venue = get_venue(args.venue)
        except VenueError as e:
            print(f"error: {e}", file=sys.stderr)
            return EXIT_USAGE
        origin = venue.origin or "built in"
        print(f"{venue.name} ({venue.key}) — {origin}\n")
        print(venue.json_spec())
        print("\n--- review form shown to reviewers ---\n")
        print(venue.form_text().rstrip())
        return 0

    print("Built-in venues:")
    for v in VENUES.values():
        print(f"  {v.key:<12} {v.name:<22} {_scale_summary(v)}")
    found = custom.list_custom()
    print("\nCustom venues:" if found else "\nNo custom venues yet.")
    for path, cv, err in found:
        if cv is None:
            print(f"  {path.stem:<12} INVALID — {err}")
        else:
            print(f"  {cv.key:<12} {cv.name:<22} {_scale_summary(cv)}  ({path})")
    print("\nSearched: " + " · ".join(str(d) for d in custom.search_dirs()))
    print("Add one:  prebuttal venues new cvpr   (or --from icml to copy a built-in form)")
    return 0


def _backend_models(name: str) -> int:
    from .modelscan import BACKENDS, scan

    if name not in BACKENDS:
        print(f"error: unknown backend '{name}' — one of: {', '.join(BACKENDS)}", file=sys.stderr)
        return EXIT_USAGE
    (listing,) = scan(only=name)
    print(listing.render(max_rows=60))
    print(
        f'\nUse one per reviewer in prebuttal.toml (backend = "{name}", model = "<id>"), '
        "or for every role of one run: prebuttal run ... --model <id>"
    )
    return EXIT_OK


def cmd_models(args) -> int:
    """Hidden 0.4 alias: every backend's models at once."""
    from .modelscan import render, scan

    _log("[prebuttal] `models` is now `prebuttal backends <name>`; this alias goes in 0.6")
    print(render(scan()))
    return EXIT_OK


# ------------------------------------------------------- interactive plan flow


def _is_interactive() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:  # pragma: no cover - exotic stdio
        return False


def _menu(prompt: str, options: list[str], default: int = 1) -> int:
    """Numbered text menu — works in every terminal (cmd included), no deps."""
    for i, opt in enumerate(options, 1):
        mark = "*" if i == default else " "
        print(f" {mark} {i}) {opt}")
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if not raw:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw)
        print(f"  (enter a number 1-{len(options)}, or Enter for the default)")


def _model_options(backend: str) -> list[str]:
    """Model choices for a backend; empty list = nothing to choose."""
    import os

    from .modelscan import (
        _CLAUDE_ALIASES,
        anthropic_models,
        gemini_models,
        openai_models,
    )
    from .providers.ollama import ollama_base_url, ollama_models

    if backend in ("auto", "agent-codex", "relay"):
        return []
    if backend == "agent-claude":
        return ["(CLI decides)", *list(_CLAUDE_ALIASES)]

    def _with_default(models: list[str] | None, first: str = "(backend default)") -> list[str]:
        return [first, *(models or [])]

    if backend == "api-gemini":
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        return _with_default(gemini_models(key) if key else None)
    if backend == "api-openai":
        key = os.environ.get("OPENAI_API_KEY")
        return _with_default(openai_models(key) if key else None)
    if backend == "api-anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY")
        return _with_default(anthropic_models(key) if key else None)
    if backend == "ollama":
        return ["(first installed)", *ollama_models(ollama_base_url())]
    if backend == "api-openrouter":
        from .modelscan import openrouter_catalog

        cat = openrouter_catalog()
        return ["(backend default)", *(cat[0] if cat else [])]
    return []


def _edit_reviewers(cfg, statuses) -> None:
    """Numbered-menu wizard over personas / backends / models (in place)."""
    from .personas import available_personas
    from .providers import auto_candidates

    backend_options = ["auto"] + [s.backend for s in auto_candidates(statuses, cfg)] + ["relay"]

    def _pick_backend(current: str) -> str:
        default = backend_options.index(current) + 1 if current in backend_options else 1
        return backend_options[_menu("  backend", backend_options, default) - 1]

    def _pick_model(current: str, backend: str) -> str:
        choices = _model_options(backend)
        if not choices:
            choices = ["(no model — backend default)"]
        models = [*choices, "(type a custom model id)"]
        default_idx = models.index(current) + 1 if current in models else 1
        pick = _menu("  model", models, default_idx)
        if pick == len(models):
            return input("  model id: ").strip()
        chosen = models[pick - 1]
        return "" if chosen.startswith("(") else chosen

    for r in cfg.reviewers:
        print(f"\n== {r.id} — persona {r.persona}, backend {r.backend} ==")
        personas = available_personas()
        dp = personas.index(r.persona) + 1 if r.persona in personas else 1
        r.persona = personas[_menu("  persona", personas, dp) - 1]
        r.backend = _pick_backend(r.backend)
        r.model = _pick_model(r.model, r.backend)

    print("\n== AC — persona area_chair ==")
    cfg.ac.backend = _pick_backend(cfg.ac.backend)
    cfg.ac.model = _pick_model(cfg.ac.model, cfg.ac.backend)


def cmd_key(args) -> int:
    import getpass

    if args.key_cmd == "status":
        _log("[prebuttal] `key status` is now part of `prebuttal backends`; this alias goes in 0.6")
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


def _config_trusted(
    cfg, backends: list[tuple[str, str]], *, pinned: bool, relay: bool = False
) -> bool:
    """Consent gate for an auto-discovered prebuttal.toml (see prebuttal.trust).

    It may come with someone else's paper repo or an unpacked arXiv source:
    running its commands, sending the paper to the provider it pins, or
    writing outside the project needs a yes — once per file content.  An
    explicit ``--config`` counts as trust; non-interactive runs refuse.
    `-y` deliberately does not bypass this (scripts add -y routinely).
    """
    from . import trust

    lines = trust.concerns(cfg, backends, pinned=pinned, relay=relay)
    if not lines or trust.is_trusted(cfg.config_path):
        return True
    _log(
        f"[prebuttal] {cfg.config_path} (found in the current directory, not passed with "
        "--config) will, with your paper as input:\n" + "\n".join(f"  {ln}" for ln in lines)
    )
    if _is_interactive():
        try:
            answer = input(
                "Use this file's settings? Only say yes if you wrote or trust it "
                "(asked again if it changes). [y/N]: "
            )
        except EOFError:
            answer = ""
        if answer.strip().lower() in ("y", "yes"):
            trust.remember(cfg.config_path)
            return True
        _log("aborted: config not trusted")
        return False
    print(
        "error: refusing to use these settings from a config that was not passed "
        f"explicitly. If you trust it, re-run with --config {cfg.config_path}",
        file=sys.stderr,
    )
    return False


def cmd_run(args) -> int:
    cfg = load_config(args.config)
    backend = args.backend
    if backend is None and (backend := env_backend()) is not None:
        _log(f"[prebuttal] backend '{backend}' for all roles (from ${BACKEND_ENV})")
    cfg = apply_overrides(
        cfg,
        venue=args.venue,
        seed=args.seed,
        backend=backend,
        model=args.model,
        reviewers_count=args.reviewers,
        effort=args.effort,
    )
    venue = get_venue(cfg.venue)
    if venue.custom:
        _log(f"[prebuttal] venue: {venue.name} (custom, {venue.origin})")
    # validate output choices before any (possibly paid) review runs
    try:
        formats = parse_formats(args.format) if args.format else cfg.output_formats
        if args.project:
            normalize_key(args.project)
    except (ValueError, ProjectError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USAGE

    _log(f"[prebuttal] ingesting {args.paper} ...")
    try:
        if args.figures:
            cfg.figures = True
        paper = ingest(args.paper, figure_images=cfg.max_figures if cfg.figures else 0)
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
    preflight = _preflight(args.paper, venue)
    paper.warnings += preflight
    for w in preflight:
        _log(f"[prebuttal] {w}")

    statuses = scan_backends(cfg)
    try:
        resolved, ac = resolve_backends(cfg, statuses)
    except NoBackendError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_NO_BACKEND

    uses_relay = any(b == "relay" for (_r, b, _m) in resolved) or ac[0] == "relay"
    host_agent = detect_host_agent()
    if host_agent and not uses_relay:
        _log("[prebuttal] hint: " + RELAY_AGENT_HINT.format(agent=host_agent))

    pack = render_pack(paper, budget_chars=cfg.budget_chars)

    if args.dry_run:
        print(render_dry_run(cfg, resolved, ac, len(pack), statuses))
        return EXIT_OK

    # Plan confirmation: only when something is still on `auto` (ambiguity to
    # resolve), never in non-interactive contexts (CI/pipes), skippable with -y.
    any_auto = cfg.ac.backend == "auto" or any(r.backend == "auto" for r in cfg.reviewers)
    if any_auto and not args.yes:
        plan = render_dry_run(cfg, resolved, ac, len(pack), statuses)
        if _is_interactive():
            try:
                while True:
                    print("\n" + plan)
                    choice = (
                        input("[Enter] run with this plan · [e] edit reviewers · [n] abort: ")
                        .strip()
                        .lower()
                    )
                    if choice == "n":
                        _log("aborted by user")
                        return EXIT_USAGE
                    if choice == "e":
                        _edit_reviewers(cfg, statuses)
                        resolved, ac = resolve_backends(cfg, statuses)
                        uses_relay = (
                            any(b == "relay" for (_r, b, _m) in resolved) or ac[0] == "relay"
                        )
                        plan = render_dry_run(cfg, resolved, ac, len(pack), statuses)
                        continue
                    break
            except EOFError:
                _log("aborted (no input available)")
                return EXIT_USAGE
        else:
            _log(
                "[prebuttal] auto mode (non-interactive) — plan follows; "
                "preview with --dry-run, silence with -y:"
            )
            _log(plan)

    from .trust import pinned_by_file

    roles = [(b, m) for (_r, b, m) in resolved] + [ac]
    if not _config_trusted(cfg, roles, pinned=pinned_by_file(args.backend), relay=uses_relay):
        return EXIT_USAGE

    providers = {}
    try:
        for rid, backend, model in resolved:
            providers[rid] = build_provider(backend, model, cfg, effort=role_effort(cfg, rid))
        ac_provider = build_provider(ac[0], ac[1], cfg, effort=role_effort(cfg, "AC"))
    except ProviderError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_NO_BACKEND

    custom = sorted({b for b, _m in roles if b.startswith("agent-") and b[6:] in cfg.agents})
    if custom and key_store.keys_path().is_file():
        # built-in agents get no file-reading tool; prebuttal can't do that for these
        _log(
            f"[prebuttal] note: {', '.join(custom)} run as configured — if they can read "
            f"files, a paper's hidden text could steer them to {key_store.keys_path()} "
            "(see SECURITY.md)"
        )

    if uses_relay:
        _log(
            f"[prebuttal] relay mode: review requests are spooled to '{cfg.relay_dir}/' — "
            f"answer each <stem>.req.md by writing JSON to <stem>.ans.md "
            f"(protocol: {cfg.relay_dir}/README.txt; "
            f"waiting up to {cfg.relay_timeout_s}s per call). "
            "For automatic reviews instead, install claude/codex CLI or set GEMINI_API_KEY."
        )

    interrupted = False
    try:
        report = run_report(paper, cfg, venue, providers, ac_provider, log=_log)
    except RunInterrupted as e:
        # keep what finished (and was paid for): archive it so `retry` can complete it
        if e.report is None or not any(r.parse_ok for r in e.report.reviews):
            raise
        _log("\n[prebuttal] interrupted — saving the reviews that finished")
        report, interrupted = e.report, True

    # Archive first, best-effort: a failure to archive never fails the
    # review, and a bad output path afterwards can't lose a (paid) review.
    project = slugify(paper.title)
    with contextlib.suppress(OSError, ProjectError):
        project = assign_project(args.paper, paper.title, args.project, register=not args.no_save)
    note = args.note.strip()
    if interrupted:
        note = f"{note} (interrupted)".strip() if note else "interrupted"
    rc = _deliver(
        report,
        venue,
        cfg,
        project=project,
        note=note,
        formats=formats,
        out_dir=args.out_dir if args.out_dir is not None else cfg.output_dir,
        json_path=args.json,
        stdout=args.stdout,
        save=not args.no_save,
    )
    return 130 if interrupted else rc


def _deliver(
    report,
    venue,
    cfg,
    *,
    project: str,
    note: str,
    formats: tuple[str, ...],
    out_dir: str,
    json_path: str | None,
    stdout: bool,
    save: bool,
) -> int:
    """Render, archive and write a finished report; print the summary; exit code."""
    md = render_markdown(report, venue)
    json_str = dumps_json(report, venue)
    html_str = render_share_html(report, venue, cfg.repo_url)
    texts = {"md": md, "html": html_str, "json": json_str}

    rec = None
    prev = None
    if save:
        try:
            prev = next((r for r in load_history() if r.project == project), None)
            rec = save_run(
                report, venue, cfg, md=md, json_str=json_str, html=html_str,
                project=project, note=note,
            )  # fmt: skip
        except OSError as e:
            _log(f"[prebuttal] warning: could not archive this run ({e})")

    written: list[Path] = []
    try:
        if out_dir:
            _dir, written = write_local(
                Path(out_dir), project, venue.key, {f: texts[f] for f in formats}
            )
        if json_path:
            jp = Path(json_path)
            jp.parent.mkdir(parents=True, exist_ok=True)
            jp.write_text(json_str, encoding="utf-8")
            written.append(jp)
    except OSError as e:
        print(f"error: cannot write report: {e}", file=sys.stderr)
        if rec is not None:
            print(f"The review is archived: `prebuttal open {rec.label}`", file=sys.stderr)
        return EXIT_USAGE

    agg = report.aggregate
    scale = venue.rating_field.max
    if agg.mean is not None:
        print(
            f"\nPredicted: {agg.mean:g}/{scale:g} (σ {agg.std:g}, range {agg.min:g}–{agg.max:g})"  # noqa: RUF001
        )
    else:
        print("\nPredicted: n/a (no parseable ratings)")
    if rec is not None:
        if (
            prev is not None
            and prev.mean is not None
            and agg.mean is not None
            and prev.scale == scale
        ):
            print(
                f"Change:   {agg.mean - prev.mean:+g} vs {prev.label} "
                f"({prev.mean:g} → {agg.mean:g})"
            )
        print(f"Saved:    {rec.label}")
    for i, it in enumerate(report.meta.action_plan[:3]):
        text = it.issue if len(it.issue) <= 90 else it.issue[:89] + "…"
        print(f"{'Fix first:' if i == 0 else '':<10} [{it.priority}] {text}")
    for i, path in enumerate(written):
        print(f"{'Report:' if i == 0 else '':<10}{path}")
    if rec is not None:
        nxt = "prebuttal open · prebuttal plan · prebuttal dashboard"
        if rec.run_no > 1:
            nxt = "prebuttal diff · " + nxt
        print(f"Next:     {nxt}")
    if stdout:
        print()
        print(md)

    failed = [r for r in report.reviews if not r.parse_ok]
    for r in failed:
        _log(f"[prebuttal] {r.reviewer_id} failed: {(r.error or 'no usable review')[:160]}")
    if not report.meta.parse_ok:
        _log(f"[prebuttal] AC failed: {(report.meta.error or 'no usable meta-review')[:160]}")
    if failed and len(failed) < len(report.reviews):
        _log(
            f"[prebuttal] the report uses the {len(report.reviews) - len(failed)} reviews that "
            "finished. Overloaded backends usually recover within minutes: "
            + (
                f"`prebuttal retry {rec.label}` re-runs only the failed reviewers"
                if rec is not None
                else "re-run later"
            )
            + ", or pick another model / backend (--model, --backend)."
        )
    if len(failed) == len(report.reviews):
        return EXIT_ALL_FAILED
    if failed or not report.meta.parse_ok:
        return EXIT_PARTIAL
    return EXIT_OK


def cmd_retry(args) -> int:
    """Re-run the failed roles exactly as configured in the archived run: same
    text, figures, backends, models and seeds. Nothing to choose (commitment 4)."""
    from .retry import (
        RetryError,
        failed_reviewers,
        load_figures,
        load_pack,
        retry_report,
        venue_for_retry,
    )

    rec = _resolve_run_or_exit(args.run)
    if rec is None:
        return EXIT_USAGE
    try:
        data = json.loads((rec.dir_path / "report.json").read_text(encoding="utf-8"))
        old = report_from_dict(data)
    except (OSError, ValueError, KeyError) as e:
        print(f"error: archived report.json for {rec.label} is unreadable ({e})", file=sys.stderr)
        return EXIT_USAGE
    targets = failed_reviewers(old)
    if not targets and old.meta.parse_ok:
        print(f"{rec.label}: every reviewer and the AC finished — nothing to retry")
        return EXIT_OK

    cfg = load_config(None)
    try:
        venue = venue_for_retry(data)
        pack = load_pack(rec.dir_path)
    except RetryError as e:
        print(f"error: cannot retry {rec.label}: {e}", file=sys.stderr)
        return EXIT_USAGE

    roles = [
        (r.reviewer_id, r.backend, r.model, r.effort) for r in (old.reviews[i] for i in targets)
    ] + [("AC", old.meta.backend, old.meta.model, old.meta.effort)]
    uses_relay = any(b == "relay" for (_r, b, _m, _e) in roles)
    if not _config_trusted(
        cfg, [(b, m) for (_r, b, m, _e) in roles], pinned=False, relay=uses_relay
    ):
        return EXIT_USAGE
    try:
        built = {rid: build_provider(b, m, cfg, effort=e) for rid, b, m, e in roles}
    except ProviderError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_NO_BACKEND
    ac_provider = built.pop("AC")
    names = ", ".join(old.reviews[i].reviewer_id for i in targets) or "none"
    _log(f"[prebuttal] retrying {rec.label}: reviewers {names}, then the AC")

    report = retry_report(
        data, pack, venue, cfg, built, ac_provider, _log, load_figures(rec.dir_path)
    )
    return _deliver(
        report,
        venue,
        cfg,
        project=rec.project,
        note=f"retry of {rec.label}",
        formats=cfg.output_formats,
        out_dir=cfg.output_dir,
        json_path=None,
        stdout=False,
        save=True,
    )


def _utf8_stdio() -> None:
    """Output contains arrows, sigma and curly quotes; on Windows a redirected stdout/stderr (> log,
    pipes, CI) defaults to the ANSI code page (cp1252) and would crash."""
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        if enc != "utf8" and hasattr(stream, "reconfigure"):
            with contextlib.suppress(Exception):  # exotic replaced streams
                stream.reconfigure(encoding="utf-8", errors="replace")


# Flags removed in 0.2 — explain the replacement instead of a bare argparse error.
_REMOVED_FLAGS = {
    "--share": "HTML reports are written by default now; drop --share",
    "--out": (
        "each run now gets its own folder under prebuttal-reports/<project>/ "
        "(nothing is overwritten); use --out-dir DIR for another location, "
        "--json PATH for a file at a fixed path, or `prebuttal export -o FILE` afterwards"
    ),
}


def _removed_flag(argv: list[str]) -> str | None:
    for tok in argv:
        name = tok.split("=", 1)[0]
        if name in _REMOVED_FLAGS:
            return f"error: {name} was removed — {_REMOVED_FLAGS[name]}"
    return None


def main(argv=None) -> int:
    _utf8_stdio()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["run"] and (msg := _removed_flag(argv)):
        print(msg, file=sys.stderr)
        return EXIT_USAGE
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
        commands = {
            "projects": cmd_projects,
            "runs": cmd_runs,
            "show": cmd_show,
            "plan": cmd_plan,
            "open": cmd_open,
            "diff": cmd_diff,
            "note": cmd_note,
            "rm": cmd_rm,
            "export": cmd_export,
            "dashboard": cmd_dashboard,
            "retry": cmd_retry,
            "check": cmd_check,
        }
        if args.cmd in commands:
            return commands[args.cmd](args)
        if args.cmd == "key":
            return cmd_key(args)
        if args.cmd == "models":
            return cmd_models(args)
        if args.cmd == "venues":
            return cmd_venues(args)
        return cmd_run(args)
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
