"""Shared helpers: config, JSONL I/O, path harvesting regexes, and the condensed-writer state."""

import json
import os
import re
import tomllib
from datetime import UTC, datetime
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parent.parent
HOME_ENV = "RESEARCHATLAS_HOME"


class ConfigError(Exception):
    """The configuration file is missing or invalid."""


def default_home():
    """Atlas home: $RESEARCHATLAS_HOME, else the source checkout atlaslib runs from, else ~/.researchatlas."""
    env = os.environ.get(HOME_ENV)
    if env:
        return Path(env).expanduser().resolve()
    if (SOURCE_DIR / "pyproject.toml").is_file() and (SOURCE_DIR / "atlas.py").is_file():
        return SOURCE_DIR
    return Path.home() / ".researchatlas"


def _expand(value):
    return os.path.expanduser(value) if isinstance(value, str) else value


def _expand_paths(cfg):
    """Expand a leading ~ in every configured path (sources, project roots, path roots, abbreviations)."""
    src = cfg.setdefault("sources", {})
    for key, value in list(src.items()):
        src[key] = _expand(value)
    cop = src.get("copilot")
    if isinstance(cop, dict):
        for key in ("chat_storage", "agent_state", "vscode_storage"):
            cop[key] = _expand(cop.get(key))
        cop["chat_dirs"] = [{k: _expand(v) for k, v in d.items()} for d in cop.get("chat_dirs") or []]
        cop["workspace_cwd"] = {k: _expand(v) for k, v in (cop.get("workspace_cwd") or {}).items()}
    proj = cfg["project"]
    for key in ("roots", "cwd_also", "exclude_cwd"):
        if key in proj:
            proj[key] = [_expand(v) for v in proj[key]]
    cfg["paths"]["roots"] = [_expand(v) for v in cfg["paths"]["roots"]]
    abbrev = cfg.setdefault("knowledge", {}).get("abbreviations", {})
    cfg["knowledge"]["abbreviations"] = {k: _expand(v) for k, v in abbrev.items()}


def load_config(path=None):
    """Load config.toml. Relative work/knowledge/ledger/mirror paths resolve against the config file's folder."""
    path = Path(path).expanduser() if path else default_home() / "config.toml"
    if not path.is_file():
        raise ConfigError(f"no config file at {path}. Create one with `researchatlas init`, or pass --config.")
    with open(path, "rb") as fh:
        try:
            cfg = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path}: {exc}") from None
    for section in ("project", "paths", "limits"):
        if section not in cfg:
            raise ConfigError(f"{path}: missing [{section}] section")
    home = path.resolve().parent
    cfg["home"] = home
    _expand_paths(cfg)
    proj = cfg["project"]
    proj["work_dir"] = home / proj["work_dir"]
    proj["knowledge_dir"] = home / proj["knowledge_dir"]
    # Review ledger (D25): committed next to knowledge/, unless configured elsewhere.
    proj["review_ledger"] = (
        home / proj["review_ledger"]
        if proj.get("review_ledger")
        else proj["knowledge_dir"].parent / "reviewed_sessions.jsonl"
    )
    cop = cfg["sources"].get("copilot")
    if isinstance(cop, dict) and cop.get("chat_storage"):
        cop["chat_storage"] = str(home / cop["chat_storage"])
    return cfg


def work_paths(cfg):
    """Locations of the generated intermediates (docs/04_mvp_spec.md, Layout)."""
    w = cfg["project"]["work_dir"]
    return {
        "work": w,
        "sessions_dir": w / "sessions",
        "sessions_index": w / "sessions.jsonl",
        "pathhits_dir": w / "pathhits",
        "paths": w / "paths.jsonl",
    }


def read_jsonl(path):
    """Yield parsed records; skip blank or malformed lines (live files may end mid-line)."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def walk_jsonl(path):
    """Yield (line_no, record) for each parseable line; skip malformed or partial lines."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield n, json.loads(line)
            except json.JSONDecodeError:
                continue


def read_json(path):
    """Small JSON file (e.g. a subagent .meta.json); {} if missing or malformed."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(s):
    """ISO-8601 UTC string (any fraction) to aware datetime, or None."""
    if not isinstance(s, str) or len(s) < 19:
        return None
    try:
        return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def collapse_ws(text):
    return " ".join(str(text).split())


MD_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$", re.M)
BLANK_RUN_RE = re.compile(r"\n\s*\n(\s*\n)+")


def tidy_body(text):
    """Demote markdown headings inside message text to bold (only '### <ts> <label>' lines are
    section headings in condensed files) and collapse runs of blank lines."""
    return BLANK_RUN_RE.sub("\n\n", MD_HEADING_RE.sub(r"**\1**", text))


def truncate(text, limit):
    """Cut text to limit chars and mark the cut (docs/04 §1, limits in config.toml)."""
    if limit is None or len(text) <= limit:
        return text
    return text[:limit] + f" …[truncated {len(text) - limit} chars]"


# Path body stops at whitespace, quotes, backticks, <>|,;{}[]*?$ (docs/02 D17), plus ':' and '\'
# (grep "file:line:" suffixes and JSON/JS escapes otherwise glue onto the path).
PATH_STOP = "\\s\"'`<>|,;:{}\\[\\]*?$\\\\"
# Parentheses are not stops: names like "1x1(iw612)" and "tier1a_feat_PCA_(10D).png" occur. A "(...)" group is
# taken whole (PATH_GROUP), so a ")" with no "(" inside the path (prose, "func(path, x)") still ends it.
PATH_GROUP = r"\([^" + PATH_STOP + r"()]*\)"
# Recording folders are named "YYYY-MM-DD HH:MM:SS" (e.g. exports/.../files/2026-08-13 05:37:04),
# or "YYYY-MM-DD HH_MM_SS", so a " HH:MM:SS" / " HH_MM_SS" right after a date stays part of the path despite the
# space and colons.
# A path may also start right after a literal backslash + n/t/r (doubly escaped tool output: "notice.xlsx\n/mnt/...").
PATH_RE_TMPL = (
    r"(?:(?<=file://)|(?<![\w./-])|(?<=\\[ntr]))(?:{root})(?=/|[^\w.\-]|$)"
    r"(?:[^" + PATH_STOP + r"()]|" + PATH_GROUP + r"|(?<=\d-\d\d) \d\d[:_]\d\d[:_]\d\d)*"
)
# Kind guess by extension (docs/04_mvp_spec.md §2). Anything else: "dir" if verified as a
# directory, else "other".
PATH_KINDS = [
    ("data", ".npy .npz .h5 .hdf5 .mat .csv .dat .pkl .pickle .parquet .feather .bin .json .txt .wav"),
    ("notebook", ".ipynb"),
    ("code", ".py .sh .cc .h .cpp"),
    ("doc", ".md .pdf .html"),
    ("config", ".yaml .yml .toml .ini"),
    ("figure", ".png .jpg .jpeg .svg"),
    ("model", ".onnx .tflite .pt .pth .ckpt"),
]
_KIND_BY_EXT = {ext: kind for kind, exts in PATH_KINDS for ext in exts.split()}


def path_regex(roots):
    """Compiled regex matching absolute paths under any of the roots (D17)."""
    alts = "|".join(re.escape(r.rstrip("/")) for r in sorted(roots, key=len, reverse=True))
    return re.compile(PATH_RE_TMPL.replace("{root}", "(?:" + alts + ")"))


# grep -n context lines glue "-<line>-<text>" onto a file name, e.g. ".../loader.py-52-#". The part before the
# suffix is cut only if it ends in a known extension (_KIND_BY_EXT), so
# ".../test_d4f.cpython-310-pytest-9.1.1.pyc" stays whole.
GREP_CONTEXT_RE = re.compile(r"^(.*?\.[A-Za-z0-9]{1,8})-\d+-.*$")


def clean_path(raw):
    """Strip trailing punctuation, normalize; None if empty or over 400 chars."""
    p = raw
    m = GREP_CONTEXT_RE.match(raw)
    if m and m.group(1)[m.group(1).rfind(".") :].lower() in _KIND_BY_EXT:
        p = m.group(1)
    p = p.rstrip(".:'/")
    if not p or len(p) > 400:
        return None
    return os.path.normpath(p)


def scan_paths(text, rx, hits):
    """Count root-prefixed absolute paths in text into hits (dict path -> count)."""
    if not isinstance(text, str) or not text:
        return
    for m in rx.finditer(text):
        p = clean_path(m.group(0))
        if p:
            hits[p] = hits.get(p, 0) + 1


def scan_obj(obj, rx, hits):
    """Scan every string in a JSON-like object (keys and values)."""
    if isinstance(obj, str):
        scan_paths(obj, rx, hits)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            scan_paths(k, rx, hits)
            scan_obj(v, rx, hits)
    elif isinstance(obj, list):
        for v in obj:
            scan_obj(v, rx, hits)


def under(path, prefixes):
    """True if path equals or lies under one of the prefixes."""
    return bool(path) and any(path == p or path.startswith(p.rstrip("/") + "/") for p in prefixes)


def new_state(rx, rx_proj, body_path, lim):
    """Per-session parse state: streams condensed body to body_path, collects hits and flags."""
    return {
        "rx": rx,
        "rx_proj": rx_proj,
        "lim": lim,
        "fh": open(body_path, "w", encoding="utf-8"),
        "hits": {},
        "n_text": 0,
        "n_user": 0,
        "wrote": False,
        "open_agent": False,
        "first_user": None,
        "start": None,
        "end": None,
        "last_ts": None,
        "agent_texts": [],
        "mention": False,
        "title": None,
        "cli": None,
        "cwd": None,
    }


def note_ts(st, ts):
    """Track session start/end and the last seen timestamp."""
    if ts is None:
        return
    st["start"] = ts if st["start"] is None or ts < st["start"] else st["start"]
    st["end"] = ts if st["end"] is None or ts > st["end"] else st["end"]
    st["last_ts"] = ts


def heading(st, label, ts, text, limit, counts=True):
    """Write one '### <ts> <label>' section with truncated text. Scans full text for paths."""
    text = (text or "").strip()
    if not text:
        return
    ts = ts or st["last_ts"]
    scan_paths(text, st["rx"], st["hits"])
    if st["rx_proj"].search(text):
        st["mention"] = True
    if st["wrote"]:
        st["fh"].write("\n")
    stamp = ts.strftime("%Y-%m-%d %H:%M") if ts else "----"
    st["fh"].write(f"### {stamp} {label}\n{tidy_body(truncate(text, limit))}\n")
    st["wrote"] = True
    st["open_agent"] = label.startswith("AGENT")
    if counts:
        st["n_text"] += 1
    if label in ("USER", "TASK (from parent)"):
        st["n_user"] += 1
        if st["first_user"] is None:
            st["first_user"] = text


def bullet(st, ts, line):
    """Append one tool-call bullet under the current AGENT section (opens one if needed)."""
    if not line:
        return
    ts = ts or st["last_ts"]
    if st["rx_proj"].search(line):
        st["mention"] = True
    if not st["open_agent"]:
        if st["wrote"]:
            st["fh"].write("\n")
        stamp = ts.strftime("%Y-%m-%d %H:%M") if ts else "----"
        st["fh"].write(f"### {stamp} AGENT\n")
        st["open_agent"] = True
        st["wrote"] = True
    st["fh"].write(f"- {line}\n")


def cmd_line(cmd, workdir, lim):
    """Format one shell command bullet body: `$ cmd` (in workdir)."""
    cmd = truncate(collapse_ws(cmd), lim["tool_input"])
    return f"`$ {cmd}`" + (f" (in {workdir})" if workdir else "")
