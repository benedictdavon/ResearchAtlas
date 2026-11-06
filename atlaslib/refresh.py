"""refresh: run extract + paths, then report sessions to review, broken cited paths, and new uncited paths.

refresh only reports. Sessions become "reviewed" through `atlas.py mark-reviewed` (review ledger, D25).
"""

import argparse
import contextlib
import io
import os
import re
import time
from collections import Counter

from atlaslib.core import ATLAS_DIR, read_jsonl, work_paths
from atlaslib.extract import cmd_extract
from atlaslib.paths import _paths_now_iso, cmd_paths, verify_paths
from atlaslib.review import condensed_file, load_ledger, pending_sessions, session_key

CITE_SPAN_RE = re.compile(r"`([^`\n]+)`")  # inline code spans in knowledge/*.md
CITE_TEMPLATE_CHARS = "<>{}*"
CITE_TEMPLATE_TOKENS = ("HH:MM:SS", "YYYY", "HHMMSS")
FREQ_CAP = 30
FREQ_SKIP_PARTS = {".agents", ".git", "__pycache__"}  # path components never reported
FREQ_SKIP_NAMES = {"SKILL.md"}

# Atlas feedback (D25): a pending session that consulted the atlas and says something in it is wrong or stale.
ATLAS_USED_RE = re.compile(r"ResearchAtlas/projects/|atlas\.py find", re.I)
ATLAS_WORD_RE = re.compile(r"atlas", re.I)  # also "ResearchAtlas"
ATLAS_CORRECTION_RE = re.compile(
    r"\b(?:differ\w*|stale|outdated|out of date|wrong|incorrect|inaccurate|newer than|mismatch\w*|"
    r"contradict\w*|not (?:in|listed in|covered by|mentioned in) (?:the )?(?:research)?atlas|"
    r"missing from (?:the )?(?:research)?atlas|atlas correction|should be updated)\b",
    re.I,
)
FEEDBACK_CAP = 5  # lines shown per session


def run_quiet(fn, cfg, args):
    """Run an existing subcommand with its stdout captured. Returns (rc, captured text)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(cfg, args)
    return rc, buf.getvalue()


CITE_PATH_END_RE = re.compile(r"(?:[^ ]|(?<=\d-\d\d) \d\d[:_]\d\d[:_]\d\d)+")


def expand_cited(span, abbrev):
    """Absolute path for one backtick span from knowledge/*.md, or None (docs/04 §4 step 3b)."""
    s = span.split(" (", 1)[0].strip()
    if not s or any(c in s for c in CITE_TEMPLATE_CHARS) or any(t in s for t in CITE_TEMPLATE_TOKENS):
        return None
    # A path ends at the first space unless the space starts a recording time (same rule as harvesting, D17),
    # so command spans like "/opt/conda/bin/python atlas.py refresh" yield just the executable.
    m = CITE_PATH_END_RE.match(s)
    s = m.group(0) if m else s
    if not s.startswith("/"):
        key, sep, rest = s.partition("/")
        if not sep or key not in abbrev:
            return None
        s = abbrev[key] + "/" + rest
    return s.rstrip("/") or None


def cited_paths(cfg):
    """(path, knowledge file name, line number) for every cited path in knowledge/*.md.

    Spans followed by a ✗ mark (documented as missing) are skipped.
    """
    abbrev = cfg["knowledge"]["abbreviations"]
    out = []
    for md in sorted(cfg["project"]["knowledge_dir"].glob("*.md")):
        with open(md, encoding="utf-8", errors="replace") as fh:
            for n, line in enumerate(fh, 1):
                for m in CITE_SPAN_RE.finditer(line):
                    if line[m.end() :].lstrip().startswith("✗"):
                        continue  # cited as known-missing; only paths that change status are reported
                    p = expand_cited(m.group(1), abbrev)
                    if p:
                        out.append((p, md.name, n))
    return out


def check_cited(cited, timeout_s):
    """Re-verify every cited path. Returns (unique count, status counts, [(path, status, error, locations)])."""
    locs = {}
    for path, fname, n in cited:
        locs.setdefault(path, []).append(f"{fname}:{n}")
    results = verify_paths(sorted(locs), timeout_s)
    bad = [
        (p, results[p]["status"], results[p]["error"], locs[p])
        for p in sorted(locs)
        if results[p]["status"] != "exists"
    ]
    return len(locs), Counter(r["status"] for r in results.values()), bad


def new_frequent_paths(rows, cited, roots, min_sessions, old_paths):
    """Verified paths that were not in paths.jsonl before this refresh (new since the last run), used in
    at least min_sessions sessions, and not covered by a cited path. Returns (count, top FREQ_CAP rows).

    Comparing against the previous path set (not last_seen) keeps one live session from re-surfacing
    every path it ever touched, and still catches new paths inside long-running sessions.

    A cited path covers itself and everything under it, except the abbreviation roots (DP, RIG, EXP),
    which cover only themselves; otherwise one root would hide every path below it.
    """
    under = [c + "/" for c in cited if c not in roots]
    out = []
    for r in rows:
        p = r["path"]
        if r.get("status") != "exists" or r.get("n_sessions", 0) < min_sessions:
            continue
        if p in old_paths:
            continue
        if any(part in FREQ_SKIP_PARTS for part in p.split("/")) or os.path.basename(p) in FREQ_SKIP_NAMES:
            continue
        if p in cited or any(p.startswith(u) for u in under):
            continue
        out.append(r)
    out.sort(key=lambda r: (-r["n_sessions"], -r.get("n_mentions", 0), r["path"]))
    return len(out), out[:FREQ_CAP]


def print_sessions(title, items):
    """One line per session; `sha=` is what mark-reviewed --report records (docs/REFRESH.md step 5)."""
    print(f"{title}: {len(items)}")
    for rec, sha, size, row in items:
        start = (rec.get("start") or "—")[:16].replace("T", " ")
        extra = ""
        if row is not None:
            delta = (size or 0) - (row.get("bytes") or 0)
            extra = (
                f"  (reviewed {row.get('reviewed')}, {delta:+,} B)"
                if row.get("bytes") is not None
                else f"  (reviewed {row.get('reviewed')})"
            )
        print(
            f"  {rec['source']}:{rec['short_id']}  {start}  {rec['kind']}  sha={sha or '-'}  "
            f"{rec.get('title') or '(no title)'}{extra}"
        )
        print(f"      {condensed_file(rec) or '(no condensed file)'}")


def atlas_feedback(path):
    """[(line no, text)] where a condensed session that consulted the atlas says the atlas is wrong or stale."""
    if not path or not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    if not any(ATLAS_USED_RE.search(line) for line in lines):
        return []
    hits = []
    for n, line in enumerate(lines, 1):
        s = line.strip()
        if s.startswith("- `$") or not ATLAS_WORD_RE.search(s) or not ATLAS_CORRECTION_RE.search(s):
            continue  # tool commands mention the atlas path, not a finding about it
        hits.append((n, s if len(s) <= 220 else s[:219] + "…"))
    return hits


def cmd_refresh(cfg, args):
    """Run extract + paths, then report what needs review (docs/04 §4). Exit 0 unless an internal error."""
    wp = work_paths(cfg)
    rc, out = run_quiet(cmd_extract, cfg, argparse.Namespace(force=False))
    if rc:
        print(out, end="")
        return 1
    index = list(read_jsonl(wp["sessions_index"]))
    ledger_path = cfg["project"]["review_ledger"]
    new, changed = pending_sessions(index, load_ledger(ledger_path))
    print(
        f"extract: {len(index)} sessions indexed; {len(index) - len(new) - len(changed)} reviewed, "
        f"{len(new)} new, {len(changed)} changed since review "
        f"(ledger {os.path.relpath(ledger_path, ATLAS_DIR)})"
    )

    old_paths = {r["path"] for r in read_jsonl(wp["paths"])} if wp["paths"].exists() else None
    t0 = time.monotonic()
    rc, out = run_quiet(cmd_paths, cfg, argparse.Namespace(no_verify=False))
    if rc:
        print(out, end="")
        return 1
    rows = list(read_jsonl(wp["paths"]))
    print(f"paths: {len(rows)} unique paths aggregated and verified ({time.monotonic() - t0:.1f} s)")
    print(f"report time: {_paths_now_iso()}")
    print()

    # Step 3a: sessions to review, then atlas feedback found in them.
    print_sessions("New sessions (not reviewed)", new)
    print_sessions("Changed since review (condensed text differs)", changed)
    print()
    feedback = [(rec, atlas_feedback(condensed_file(rec))) for rec, *_ in new + changed]
    feedback = [(rec, hits) for rec, hits in feedback if hits]
    print(
        f"Atlas feedback in these sessions (consulted the atlas, then called something in it wrong or stale; "
        f"check first): {len(feedback)}"
    )
    for rec, hits in feedback:
        print(f"  {session_key(rec)}  {os.path.relpath(condensed_file(rec), ATLAS_DIR)}")
        for n, text in hits[:FEEDBACK_CAP]:
            print(f"      :{n}  {text}")
        if len(hits) > FEEDBACK_CAP:
            print(f"      ({len(hits) - FEEDBACK_CAP} more)")

    # Step 3b: cited paths.
    cited = cited_paths(cfg)
    abbrev_roots = {v.rstrip("/") for v in cfg["knowledge"]["abbreviations"].values()}
    print()
    if args.no_verify_cited:
        print("Cited paths in knowledge/*.md: verification skipped (--no-verify-cited)")
    else:
        n_unique, counts, bad = check_cited(cited, cfg["paths"]["verify_timeout_s"])
        print(
            f"Cited paths in knowledge/*.md: {n_unique} unique; "
            + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        )
        print(f"Cited paths no longer OK (missing or unreachable): {len(bad)}")
        for p, status, err, where in bad:
            print(f"  {status}  {p}  <- {', '.join(where)}" + (f"  ({err})" if err else ""))

    # Step 3c: frequent paths not yet cited.
    print()
    if old_paths is None:
        print("New paths not yet in knowledge/: skipped (no previous paths.jsonl)")
    else:
        n_cand, shown = new_frequent_paths(
            rows, {p for p, _, _ in cited}, abbrev_roots, cfg["knowledge"]["new_path_min_sessions"], old_paths
        )
        print(
            f"New paths not yet in knowledge/ (exists, n_sessions >= "
            f"{cfg['knowledge']['new_path_min_sessions']}, not in paths.jsonl before this refresh): "
            f"{n_cand}; showing {len(shown)}"
        )
        for r in shown:
            print(f"  {r['n_sessions']:4d} sess  last {r['last_seen'][:16].replace('T', ' ')}  {r['path']}")

    print()
    print(
        f"Next: update {cfg['project']['knowledge_dir']}/ from this report (docs/prompts/incremental_update.md), "
        "then: atlas.py mark-reviewed --report <this report>"
    )
    return 0
