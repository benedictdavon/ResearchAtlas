"""ResearchAtlas CLI: mine agent transcripts into a verified research knowledge base.

Subcommands (see docs/cli.md):
  init      create a config.toml in the atlas home from the bundled template
  extract   condensed per-session markdown + sessions.jsonl + per-session path hits
  import-copilot  receive a selective PC chat archive; optionally run extract
  paths     aggregate path hits into paths.jsonl and verify each path (timeout-guarded)
  refresh   run extract + paths, then report sessions to review (new or changed since review), atlas
            feedback in them, broken cited paths and new uncited paths. Writes no review state
  mark-reviewed  record sessions as covered by knowledge/ in the review ledger (D25)
  find      search knowledge/ (by section), paths.jsonl and condensed sessions

Stdlib only; Python 3.11+. The atlas home holds config.toml, work/ and the knowledge base: $RESEARCHATLAS_HOME,
else the source checkout when run from one, else ~/.researchatlas.
"""

import argparse
import sys
from importlib import resources
from pathlib import Path

from atlaslib import __version__
from atlaslib.copilot_import import cmd_import_copilot
from atlaslib.core import HOME_ENV, ConfigError, default_home, load_config
from atlaslib.extract import cmd_extract
from atlaslib.find import cmd_find
from atlaslib.paths import cmd_paths
from atlaslib.refresh import cmd_refresh
from atlaslib.review import cmd_mark_reviewed


def cmd_init(args):
    """Copy the bundled config template into the atlas home; never overwrite an existing config."""
    home = Path(args.home).expanduser() if args.home else default_home()
    dest = home / "config.toml"
    if dest.exists():
        print(f"{dest} already exists; leaving it unchanged.")
        return 0
    home.mkdir(parents=True, exist_ok=True)
    dest.write_text(resources.files("atlaslib").joinpath("config.example.toml").read_text())
    print(f"Wrote {dest}. Edit its source and project paths, then run `researchatlas refresh`.")
    if home.resolve() != default_home().resolve():
        print(f"This is not the default home: set {HOME_ENV}={home} or pass --config {dest}.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="researchatlas", description=__doc__.splitlines()[0])
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    ap.add_argument("--config", help="path to config.toml (default: <atlas home>/config.toml)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="create config.toml in the atlas home from the bundled template")
    p.add_argument("--home", help="folder to initialise (default: the atlas home)")

    p = sub.add_parser("extract", help="condense transcripts into work/<project>/sessions/")
    p.add_argument("--force", action="store_true", help="re-extract even if raw file is unchanged")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("import-copilot", help="import selected PC Copilot logs into the workspace mirror")
    p.add_argument("archive", help="ZIP produced by tools/copilot_sync.py")
    p.add_argument("--extract", action="store_true", help="also condense/index sessions after importing")
    p.set_defaults(func=cmd_import_copilot)

    p = sub.add_parser("paths", help="aggregate and verify harvested paths into paths.jsonl")
    p.add_argument("--no-verify", action="store_true", help="re-aggregate only; keep the previous verification fields")
    p.set_defaults(func=cmd_paths)

    p = sub.add_parser(
        "refresh",
        help="run extract + paths, then report sessions to review, broken cited paths, "
        "and new uncited paths (docs/cli.md, refresh); writes no review state",
    )
    p.add_argument("--no-verify-cited", action="store_true", help="skip re-verifying paths cited in knowledge/*.md")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="accepted for old instructions; refresh never records sessions as reviewed (D25)",
    )
    p.set_defaults(func=cmd_refresh)

    p = sub.add_parser("mark-reviewed", help="record sessions as covered by knowledge/ (review ledger, D25)")
    p.add_argument("ids", nargs="*", help="session ids: <source>:<id prefix> or a bare id prefix")
    p.add_argument(
        "--report",
        help="refresh report: mark the sessions it lists (or only the given ids) at the "
        "content it listed; sessions that changed since stay pending",
    )
    p.add_argument("--note", default="", help="short note stored with each row (e.g. the update it went into)")
    p.set_defaults(func=cmd_mark_reviewed)

    p = sub.add_parser("find", help="search knowledge/, paths.jsonl and condensed sessions (docs/cli.md, find)")
    p.add_argument(
        "term",
        nargs="+",
        help="words; all must occur in one knowledge section, path or session message (case-insensitive)",
    )
    p.add_argument(
        "--limit", type=int, default=10, help="results shown per group: sections, paths, session files (default 10)"
    )
    p.set_defaults(func=cmd_find)

    args = ap.parse_args(argv)
    if args.cmd == "init":
        return cmd_init(args)
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"researchatlas: {exc}", file=sys.stderr)
        return 2
    return args.func(cfg, args) or 0
