"""Review ledger: which sessions the knowledge files already cover, and at which condensed content (D25).

One row per reviewed session in `[project].review_ledger` (committed next to knowledge/):
  {"session": "<source>:<full id>", "reviewed": "YYYY-MM-DD", "sha": "<12 hex>"|null, "bytes": int|null, "note": "..."}
`sha`/`bytes` describe the condensed transcript that was reviewed (null: the session had no condensed text).
A session is pending when it has no row, or its condensed text no longer matches the reviewed sha.
"""

import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from atlaslib.core import read_jsonl, work_paths

SHA_LEN = 12
# Session lines printed by refresh (print_sessions); mark-reviewed --report parses them back.
REPORT_LINE_RE = re.compile(r"^  ([a-z]+):(\S+)\s.*\bsha=(\w+|-)")


def session_key(rec):
    return f"{rec['source']}:{rec['id']}"


def condensed_file(rec, home=None):
    """Condensed transcript path; index paths are relative to the atlas home."""
    cp = rec.get("condensed_path")
    return os.path.normpath(Path(home or "") / cp) if cp else None


def condensed_digest(rec, home=None):
    """(sha, bytes) of a session's condensed transcript, or (None, None) when it has none."""
    path = condensed_file(rec, home)
    if not path or not os.path.isfile(path):
        return None, None
    with open(path, "rb") as fh:
        data = fh.read()
    return hashlib.sha256(data).hexdigest()[:SHA_LEN], len(data)


def load_ledger(path):
    """{session key: row}. Missing file = nothing reviewed yet."""
    path = Path(path)
    return {r["session"]: r for r in read_jsonl(path) if r.get("session")} if path.exists() else {}


def save_ledger(path, ledger):
    """Sorted by session key (stable git diffs); temp file + os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        for key in sorted(ledger):
            fh.write(json.dumps(ledger[key], ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def pending_sessions(index_rows, ledger, home=None):
    """Split indexed sessions into (new, changed). Each item is (record, sha, bytes, reviewed row or None)."""
    new, changed = [], []
    for rec in index_rows:
        sha, size = condensed_digest(rec, home)
        row = ledger.get(session_key(rec))
        if row is None:
            new.append((rec, sha, size, None))
        elif row.get("sha") != sha:
            changed.append((rec, sha, size, row))
    return new, changed


def parse_report(path):
    """{session key prefix ("source:short_id"): sha or None} for every session line in a refresh report."""
    out = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = REPORT_LINE_RE.match(line)
            if m:
                out[f"{m.group(1)}:{m.group(2)}"] = None if m.group(3) == "-" else m.group(3)
    return out


def resolve(term, index):
    """Index keys matching one id term: "<source>:<prefix>" or a bare id prefix."""
    if ":" in term:
        src, _, pre = term.partition(":")
        return [k for k, r in index.items() if r["source"] == src and r["id"].startswith(pre)]
    return [k for k, r in index.items() if r["id"].startswith(term)]


def cmd_mark_reviewed(cfg, args):
    """Record sessions as covered by knowledge/ (docs/REFRESH.md step 5). Writes nothing on any error."""
    wp = work_paths(cfg)
    if not wp["sessions_index"].exists():
        print(f"error: {wp['sessions_index']} missing; run refresh first", file=sys.stderr)
        return 2
    index = {session_key(r): r for r in read_jsonl(wp["sessions_index"])}
    report = parse_report(args.report) if args.report else None
    terms = list(args.ids)
    if not terms:
        if report is None:
            print(
                "error: give session ids, or --report <refresh report> to mark every session it lists", file=sys.stderr
            )
            return 2
        terms = list(report)

    chosen, errors = {}, []
    for term in terms:
        keys = resolve(term, index)
        if len(keys) != 1:
            errors.append(f"{term}: {'no indexed session' if not keys else 'ambiguous: ' + ', '.join(sorted(keys))}")
            continue
        chosen[keys[0]] = term
    reported_sha = {}
    if report is not None:
        for key in chosen:
            rec = index[key]
            hit = [s for t, s in report.items() if t == f"{rec['source']}:{rec['short_id']}"]
            if not hit:
                errors.append(f"{key}: not listed in {args.report}")
            else:
                reported_sha[key] = hit[0]
    if errors:
        print("error: nothing marked.\n  " + "\n  ".join(errors), file=sys.stderr)
        return 2

    ledger_path = cfg["project"]["review_ledger"]
    ledger = load_ledger(ledger_path)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    stale, unchanged = [], 0
    for key in sorted(chosen):
        sha, size = condensed_digest(index[key], cfg["home"])
        if key in reported_sha and reported_sha[key] != sha:
            # The session changed after the report was written: record what was reviewed, so it stays pending.
            stale.append(key)
            sha, size = reported_sha[key], None
        old = ledger.get(key)
        if old and old.get("sha") == sha and not args.note:
            unchanged += 1
            continue
        ledger[key] = {
            "session": key,
            "reviewed": today,
            "sha": sha,
            "bytes": size,
            "note": args.note or (old or {}).get("note", ""),
        }
    save_ledger(ledger_path, ledger)
    print(
        f"marked {len(chosen) - unchanged} session(s) reviewed ({unchanged} already up to date) "
        f"in {os.path.relpath(ledger_path, cfg['home'])}"
    )
    for key in stale:
        print(f"  note: {key} changed after the report was written; it stays pending for its new content")
    return 0
