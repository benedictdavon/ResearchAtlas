"""find: case-insensitive search over knowledge/, paths.jsonl and condensed sessions (docs/04 §5, D26).

Knowledge files are matched per section (a heading through the next heading), so the words may sit on
different lines of one entry; the heading path counts as part of the section. Sessions are matched per
message and summarised per file. Results are ranked; --limit counts sections / paths / session files.
"""

import os
import re
import sys

from atlaslib.core import read_jsonl, work_paths

FIND_WIDTH = 200  # max chars of one matched line shown
LINES_PER_SECTION = 3  # best matching lines shown under a knowledge section
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


def snippet(line, words):
    """Stripped line cut to FIND_WIDTH chars, windowed so the first match stays in view."""
    text = line.strip()
    if len(text) <= FIND_WIDTH:
        return text
    low = text.lower()
    found = [i for i in (low.find(w) for w in words) if i >= 0]
    pos = min(found) if found else 0
    start = max(0, min(pos - 60, len(text) - FIND_WIDTH))
    body = text[start : start + FIND_WIDTH]
    if start > 0:
        body = "…" + body[1:]
    if start + FIND_WIDTH < len(text):
        body = body[:-1] + "…"
    return body


def md_sections(lines):
    """Markdown sections as (start line, heading path list, [(line no, text)]); `#` inside code fences is text."""
    sections, stack, fence = [], [], None
    cur = (1, [], [])
    for n, line in enumerate(lines, 1):
        if FENCE_RE.match(line):
            mark = FENCE_RE.match(line).group(1)
            fence = None if fence == mark else (fence or mark)
        m = None if fence or FENCE_RE.match(line) else HEADING_RE.match(line)
        if m:
            sections.append(cur)
            level = len(m.group(1))
            stack = [h for h in stack if h[0] < level] + [(level, m.group(2))]
            cur = (n, [t for _, t in stack], [])
        cur[2].append((n, line.rstrip("\n")))
    sections.append(cur)
    return [s for s in sections if s[2]]


def score_lines(body, words):
    """(lines containing every word, [(n words on line, line no, text)] for lines with any word)."""
    full, partial = 0, []
    for n, text in body:
        low = text.lower()
        k = sum(w in low for w in words)
        if k:
            partial.append((k, n, text))
            full += k == len(words)
    return full, partial


def find_knowledge(kdir, words, home):
    """Ranked knowledge sections: (rank key, file label, start line, heading path, best lines)."""
    hits = []
    for md in sorted(kdir.glob("*.md")):
        with open(md, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        rel = os.path.relpath(md, home)
        for start, path, body in md_sections(lines):
            text = (" ".join(path) + "\n" + "".join(t + "\n" for _, t in body)).lower()
            if not all(w in text for w in words):
                continue
            full, partial = score_lines(body, words)
            best = sorted(partial, key=lambda x: (-x[0], x[1]))[:LINES_PER_SECTION]
            hits.append(
                (
                    (-full, -sum(k for k, _, _ in partial), rel, start),
                    rel,
                    start,
                    path,
                    sorted(best, key=lambda x: x[1]),
                )
            )
    hits.sort(key=lambda h: h[0])
    return hits


def find_paths(path, words):
    """paths.jsonl records whose path contains every word: existing first, then most sessions."""
    if not path.is_file():
        return []
    hits = [r for r in read_jsonl(path) if all(w in (r.get("path") or "").lower() for w in words)]
    hits.sort(key=lambda r: (r.get("status") != "exists", -(r.get("n_sessions") or 0), r.get("path") or ""))
    return hits


def find_sessions(sdir, words, home):
    """Condensed sessions with a message (### section) containing every word, most matching messages first.
    Each hit: (rank key, file label, title, n matching messages, (line no, text) of the best line)."""
    hits = []
    for md in sorted(sdir.glob("*.md")):
        with open(md, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        title = lines[0].strip()[2:] if lines and lines[0].startswith("# ") else md.stem
        n_msgs, n_full, best = 0, 0, None
        msg = []
        for n, line in enumerate(lines + ["### end\n"], 1):
            if line.startswith("### "):
                text = "".join(t for _, t in msg).lower()
                if msg and all(w in text for w in words):
                    n_msgs += 1
                    full, partial = score_lines([(k, t) for k, t in msg], words)
                    n_full += full
                    top = max(partial, key=lambda x: (x[0], -x[1]))
                    if best is None or top[0] > best[0]:
                        best = top
                msg = []
            msg.append((n, line.rstrip("\n")))
        if n_msgs:
            rel = os.path.relpath(md, home)
            hits.append(((-n_full, -n_msgs, rel), rel, title, n_msgs, (best[1], best[2])))
    hits.sort(key=lambda h: h[0])
    return hits


def more(n, limit):
    if n > limit:
        print(f"  ({n - limit} more; raise --limit)")


def cmd_find(cfg, args):
    """Case-insensitive substring search; all words must occur in one section / path / message (docs/04 §5)."""
    words = [w.lower() for t in args.term for w in t.split()]
    if not words:
        print("error: empty search term", file=sys.stderr)
        return 2
    wp = work_paths(cfg)
    know = find_knowledge(cfg["project"]["knowledge_dir"], words, cfg["home"])
    paths = find_paths(wp["paths"], words)
    sess = find_sessions(wp["sessions_dir"], words, cfg["home"])
    if not (know or paths or sess):
        print(
            f"No match for '{' '.join(args.term)}' in the atlas. "
            "Don't guess a path; ask the user or search the filesystem."
        )
        return 0
    if know:
        print(f"== knowledge: {len(know)} matching sections (best first)")
        for _, rel, start, path, best in know[: args.limit]:
            shown = path[1:] if len(path) > 1 else path  # the file's title heading is implied by the file name
            print(f"  {rel}:{start}  {' > '.join(shown) or '(top of file)'}")
            for _, n, text in best:
                print(f"      :{n}  {snippet(text, words)}")
        more(len(know), args.limit)
    if paths:
        print(f"== paths.jsonl: {len(paths)} matching paths (existing first, most sessions first)")
        for r in paths[: args.limit]:
            print(f"  {r.get('path')}  status={r.get('status')} n_sessions={r.get('n_sessions')}")
        more(len(paths), args.limit)
    if sess:
        print(f"== sessions: {len(sess)} matching transcripts (leads, not verified; most matches first)")
        for _, rel, title, n_msgs, (n, text) in sess[: args.limit]:
            print(f"  {title}  [{n_msgs} msg]")
            print(f"      {rel}:{n}  {snippet(text, words)}")
        more(len(sess), args.limit)
    return 0
