"""extract: condense Codex/Claude/Copilot transcripts into work/<project>/sessions and index them.

See docs/cli.md, extract.
"""

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

from atlaslib.core import _iso, collapse_ws, path_regex, read_jsonl, under, work_paths, write_jsonl
from atlaslib.sources import SOURCES


def discover_candidates(cfg, codex_paths=None, skipped=None):
    """All sessions of every registered source, with header info only. Returns (cands, guardians).

    skipped, if given, is filled with each source's deliberately skipped count (codex guardians, copilot duplicates).
    """
    cands, skipped = [], {} if skipped is None else skipped
    for name, mod in SOURCES.items():
        found, n = mod.discover(cfg, codex_paths)
        cands += found
        skipped[name] = n
    for c in cands:
        st = c["path"].stat()
        c["size"], c["mtime"] = st.st_size, st.st_mtime
        c["key"] = (c["source"], c["id"])
    return cands, skipped.get("codex", 0)


def select_candidates(cands, cfg):
    """Selection by cwd, then by parent, per docs/cli.md, extract. Returns key -> selected_by (mention is pass C)."""
    proj, excl = cfg["project"], cfg["project"]["exclude_cwd"]
    cwd_roots = proj["roots"] + proj["cwd_also"]
    ex_ids = tuple(proj.get("exclude_ids", []))
    for c in cands:
        c["excluded"] = under(c["cwd"], excl) or bool(ex_ids and c["id"].startswith(ex_ids))
    # Children of an excluded session (subagents, forks) are excluded too (D20).
    changed = True
    while changed:
        changed = False
        out = {c["key"] for c in cands if c["excluded"]}
        for c in cands:
            if not c["excluded"] and c["parent_id"] and (c["source"], c["parent_id"]) in out:
                c["excluded"] = changed = True
    sel = {}
    for c in cands:
        if not c["excluded"] and under(c["cwd"], cwd_roots):
            sel[c["key"]] = "cwd"
    changed = True
    while changed:
        changed = False
        for c in cands:
            if c["key"] in sel or c["excluded"] or c["kind"] not in ("subagent", "fork"):
                continue
            if c["parent_id"] and (c["source"], c["parent_id"]) in sel:
                sel[c["key"]] = "parent"
                changed = True
    return sel


def mention_needles(cfg):
    return [r.encode("utf-8") for r in cfg["project"]["roots"]]


def raw_mentions(path, needles):
    """Cheap byte prefilter: a condensed text can only mention a root if the raw file contains it."""
    with open(path, "rb") as fh:
        data = fh.read()
    return any(n in data for n in needles)


def fresh(rec, c):
    """Index record still matches the raw file (size and mtime)."""
    return rec.get("raw_size") == c["size"] and rec.get("raw_mtime") == c["mtime"]


def outputs_exist(rec, pathhits_dir, home):
    """Both per-session outputs exist (condensed only if the record has one)."""
    ph = pathhits_dir / f"{rec['source']}_{rec['short_id']}.json"
    cp = rec.get("condensed_path")
    return ph.exists() and (cp is None or (home / cp).exists())


def parse_candidate(c, ctx):
    """Condense one candidate into a temp body file. Returns the parse state."""
    body = ctx["sessions_dir"] / f".{c['source']}_{c['short']}.body.tmp"
    st = SOURCES[c["source"]].condense(c, ctx, body)
    st["body"] = body
    return st


def session_title(c, st, ctx):
    """Source title (ctx holds what the source's prepare read), else first user text (80), else '(no title)'."""
    t = SOURCES[c["source"]].title(c, st, ctx)
    if not t and st["first_user"]:
        fu = collapse_ws(st["first_user"])
        t = fu[:80] + ("…" if len(fu) > 80 else "")
    return collapse_ws(t) if t else "(no title)"


def write_condensed(c, st, title, out_path, cwd, cli):
    """Header plus streamed body into out_path (atomic replace)."""
    tmp = out_path.with_name("." + out_path.name + ".tmp")
    size_mb = c["size"] / 1048576
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(f"# {c['source']}:{c['short']} — {title}\n")
        fh.write(f"- kind: {c['kind']} · source: {c['source']} · cli: {cli or '—'}\n")
        fh.write(f"- id: {c['id']} · parent: {c['parent_id'] or '—'}\n")
        fh.write(f"- cwd: {cwd or '—'}\n")
        fh.write(
            f"- start: {_iso(st['start']) if st['start'] else '—'} · end: {_iso(st['end']) if st['end'] else '—'}\n"
        )
        fh.write(f"- raw: {c['path']} ({size_mb:.2f} MB)\n\n")
        with open(st["body"], encoding="utf-8") as body:
            for line in body:
                fh.write(line)
    os.replace(tmp, out_path)


def write_pathhits(c, st, pathhits_dir):
    """Per-session path hits for the paths worker (docs/cli.md, extract and paths; D17)."""
    out = pathhits_dir / f"{c['source']}_{c['short']}.json"
    obj = {
        "source": c["source"],
        "id": c["id"],
        "short_id": c["short"],
        "start": _iso(st["start"]) if st["start"] else None,
        "end": _iso(st["end"]) if st["end"] else None,
        "hits": st["hits"],
    }
    tmp = out.with_name("." + out.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, out)


def finalize(c, st, sel_by, ctx):
    """Write condensed + pathhits for a parsed candidate and return its index record."""
    cwd = c["cwd"] or st["cwd"]
    cli = st["cli"] or c["meta"].get("cli_version")
    title = session_title(c, st, ctx)
    condensed = None
    if st["n_text"] > 0:
        out = ctx["sessions_dir"] / f"{c['source']}_{c['short']}.md"
        write_condensed(c, st, title, out, cwd, cli)
        condensed = os.path.relpath(out, ctx["home"])
    if st["body"].exists():
        os.remove(st["body"])
    write_pathhits(c, st, ctx["pathhits_dir"])
    return {
        "source": c["source"],
        "id": c["id"],
        "short_id": c["short"],
        "kind": c["kind"],
        "parent_id": c["parent_id"],
        "cwd": cwd,
        "start": _iso(st["start"]) if st["start"] else None,
        "end": _iso(st["end"]) if st["end"] else None,
        "title": title,
        "n_user_msgs": st["n_user"],
        "selected_by": sel_by,
        "condensed_path": condensed,
        "raw_path": str(c["path"]),
        "raw_size": c["size"],
        "raw_mtime": c["mtime"],
        "cli_version": cli,
    }


def remove_stale(folder, keep, pattern):
    """Delete generated files in folder that no current record references (and leftover temps)."""
    for f in folder.glob(pattern):
        if f.name not in keep:
            f.unlink()
    for f in folder.glob(".*.tmp"):
        f.unlink()


def cmd_extract(cfg, args):
    """Condense transcripts into work/<project>/sessions and index them (docs/cli.md, extract)."""
    t0 = time.time()
    wp = work_paths(cfg)
    ctx = {
        "home": cfg["home"],
        "sessions_dir": wp["sessions_dir"],
        "pathhits_dir": wp["pathhits_dir"],
        "rx": path_regex(cfg["paths"]["roots"]),
        "rx_proj": path_regex(cfg["project"]["roots"]),
        "lim": cfg["limits"],
    }
    ctx["sessions_dir"].mkdir(parents=True, exist_ok=True)
    ctx["pathhits_dir"].mkdir(parents=True, exist_ok=True)
    unsel_path = wp["work"] / "unselected.jsonl"
    prev = (
        {(r["source"], r["id"]): r for r in read_jsonl(wp["sessions_index"])} if wp["sessions_index"].exists() else {}
    )
    cache = {(r["source"], r["id"]): r for r in read_jsonl(unsel_path)} if unsel_path.exists() else {}
    skipped = {}
    cands, guardians = discover_candidates(cfg, skipped=skipped)
    sel = select_candidates(cands, cfg)
    for mod in SOURCES.values():
        mod.prepare(cfg, ctx)
    needles = mention_needles(cfg)
    stats, parsed, unsel, errors = Counter(), {}, {}, set()

    # Pass C: mention candidates (not selected by cwd or parent). Reuse what is cheap to reuse first.
    for c in cands:
        key = c["key"]
        if key in sel or c["excluded"]:
            continue
        pr = prev.get(key)
        if (
            not args.force
            and pr
            and pr.get("selected_by") == "mention"
            and fresh(pr, c)
            and outputs_exist(pr, ctx["pathhits_dir"], ctx["home"])
        ):
            sel[key] = "mention"
            continue
        cr = cache.get(key)
        if not args.force and cr and fresh(cr, c):
            stats["unselected_cached"] += 1
            unsel[key] = cr
            continue
        if not raw_mentions(c["path"], needles):
            stats["prefilter_skip"] += 1
            continue
        try:
            st = parse_candidate(c, ctx)
        except Exception as e:  # keep going; one bad transcript must not stop the run
            print(f"warning: {c['path']}: {e}", file=sys.stderr)
            errors.add(key)
            continue
        if st["mention"]:
            sel[key] = "mention"
            parsed[key] = st
        else:
            os.remove(st["body"])
            stats["unselected_parsed"] += 1
            unsel[key] = {"source": c["source"], "id": c["id"], "raw_size": c["size"], "raw_mtime": c["mtime"]}

    # Final stage: reuse or parse each selected session, write outputs.
    rows, reused, n_parsed = [], 0, 0
    for c in cands:
        sb = sel.get(c["key"])
        if not sb or c["key"] in errors:
            continue
        pr = prev.get(c["key"])
        if (
            c["key"] not in parsed
            and not args.force
            and pr
            and fresh(pr, c)
            and outputs_exist(pr, ctx["pathhits_dir"], ctx["home"])
        ):
            rec = dict(pr)
            rec["selected_by"] = sb
            reused += 1
        else:
            try:
                st = parsed.pop(c["key"], None) or parse_candidate(c, ctx)
                rec = finalize(c, st, sb, ctx)
            except Exception as e:
                print(f"warning: {c['path']}: {e}", file=sys.stderr)
                errors.add(c["key"])
                continue
            n_parsed += 1
        rows.append(rec)
        stats[(c["source"], c["kind"])] += 1
        stats["by_" + sb] += 1

    # Index, cache of unselected sessions, cleanup of stale outputs.
    rows.sort(key=lambda r: (r["start"] or "", r["source"], r["id"]))
    write_jsonl(wp["sessions_index"], rows)
    write_jsonl(unsel_path, sorted(unsel.values(), key=lambda r: (r["source"], r["id"])))
    keep_md = {Path(r["condensed_path"]).name for r in rows if r["condensed_path"]}
    keep_json = {f"{r['source']}_{r['short_id']}.json" for r in rows}
    remove_stale(ctx["sessions_dir"], keep_md, "*.md")
    remove_stale(ctx["pathhits_dir"], keep_json, "*.json")

    # Summary.
    counts = Counter(c["source"] for c in cands)
    extra = "".join(f", {counts[s]} {s}" for s in SOURCES if s not in ("codex", "claude") and counts[s])
    dups = skipped.get("copilot", 0)
    print(
        f"scanned {len(cands) + sum(skipped.values())} sessions ({counts['codex']} codex, {counts['claude']} claude"
        f"{extra}); guardians skipped {guardians}" + (f"; copilot duplicates dropped {dups}" if dups else "")
    )
    print(
        f"selected {len(rows)}: by cwd {stats['by_cwd']}, by parent {stats['by_parent']}, "
        f"by mention {stats['by_mention']}"
    )
    print(
        "per source/kind: "
        + ", ".join(f"{s} {k} {n}" for (s, k), n in sorted((k, v) for k, v in stats.items() if isinstance(k, tuple)))
    )
    print(
        f"re-used {reused}, parsed {n_parsed}; unselected: cached {stats['unselected_cached']}, "
        f"parsed {stats['unselected_parsed']}, skipped by byte prefilter {stats['prefilter_skip']}; "
        f"errors {len(errors)}"
    )
    raw_mb = sum(r["raw_size"] for r in rows) / 1048576
    cond = [cfg["home"] / r["condensed_path"] for r in rows if r["condensed_path"]]
    cond_mb = sum(p.stat().st_size for p in cond) / 1048576
    print(f"raw {raw_mb:.1f} MB (selected) vs condensed {cond_mb:.2f} MB in {len(cond)} files")
    all_paths = set()
    for r in rows:
        with open(ctx["pathhits_dir"] / f"{r['source']}_{r['short_id']}.json", encoding="utf-8") as fh:
            all_paths.update(json.load(fh)["hits"])
    print(f"pathhits: {len(rows)} files, {len(all_paths)} unique paths")
    print(f"wall {time.time() - t0:.1f} s")
    return 0
