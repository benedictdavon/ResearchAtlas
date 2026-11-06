#!/usr/bin/env python3
"""End-to-end ResearchAtlas demo on a small, fictional research project.

Builds a throwaway world in a temporary folder (or --dir):
  research/birdsong/   the research repo: raw recordings, labels, experiments
  archive/             a second data root, standing in for a network share
  agents/              synthetic Codex, Claude Code and Copilot transcripts about that project
  atlas/               the atlas home: config.toml, work/ and the knowledge base

Then it runs the real CLI the way you would: extract and verify, review, search, and finally refresh after
the project has moved on (a new session arrives and a dataset moves to the archive).

    python examples/demo/run_demo.py [--dir /tmp/atlas-demo]

Stdlib only. Nothing outside the chosen folder is read or written.
"""

import argparse
import contextlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))  # run from a source checkout without installing
from atlaslib.cli import main as atlas  # noqa: E402

CODEX_1 = "019c3a1e-5b2f-7a10-9e2d-6f1b0c4d8a01"
CLAUDE_1 = "8d2f4c1a-3e6b-4f0d-9a7c-2b5e8f1d0c34"
COPILOT_1 = "c41e9b07-6d2a-4b8e-a1f3-5c7d9e0b2a68"
CODEX_2 = "019c5f72-0a4d-7c3e-8b1f-3e9a2d6c4b07"


def jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


# --- the research project ---------------------------------------------------------------------------------------


def build_project(world):
    bs = world / "research/birdsong"
    for site in ("site_a", "site_b"):
        for n in range(3):
            f = bs / f"data/raw/2026-03-field/{site}/clip_{n:03d}.wav"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"RIFF\0\0\0\0WAVE")
    (bs / "data/labels/v2").mkdir(parents=True)
    (bs / "data/labels/v2/labels.csv").write_text("clip,species\nsite_a/clip_000.wav,erithacus_rubecula\n")
    (bs / "data/splits").mkdir(parents=True)
    (bs / "data/splits/site_folds.json").write_text('{"fold_0": ["site_a"], "fold_1": ["site_b"]}\n')
    for exp, f1 in (("exp012_cnn_baseline", 0.71), ("exp013_beats_finetune", 0.78)):
        (bs / f"experiments/{exp}").mkdir(parents=True)
        (bs / f"experiments/{exp}/results.json").write_text(json.dumps({"macro_f1": f1}) + "\n")
    (world / "archive").mkdir()
    # data/labels/v1 is mentioned in the transcripts but was deleted after relabelling, so it verifies as missing.
    return bs


# --- synthetic transcripts (formats: docs/transcript-formats.md) -------------------------------------------------


def _cx_msg(role, text, phase=None):
    part = "input_text" if role == "user" else "output_text"
    payload = {"type": "message", "role": role, "content": [{"type": part, "text": text}]}
    if phase:
        payload["phase"] = phase
    return payload


def codex_session(world, sid, ts, cwd, user, cmd, output, answer):
    day = ts[:10].replace("-", "/")
    path = world / f"agents/codex/sessions/{day}/rollout-{ts[:19].replace(':', '-')}-{sid}.jsonl"
    meta = {"id": sid, "session_id": sid, "cwd": cwd, "timestamp": ts, "cli_version": "0.161.0", "source": "cli"}
    call = {"type": "function_call", "name": "exec_command", "arguments": json.dumps({"cmd": cmd}), "call_id": "c1"}
    payloads = [
        _cx_msg("user", user),
        call,
        {"type": "function_call_output", "call_id": "c1", "output": output},
        _cx_msg("assistant", answer, "final_answer"),
    ]
    records = [{"timestamp": ts, "type": "session_meta", "payload": meta}]
    records += [{"timestamp": ts, "type": "response_item", "payload": p} for p in payloads]
    jsonl(path, records)


def claude_session(world, sid, ts, cwd, user, command, output, answer):
    path = world / "agents/claude/projects" / cwd.replace("/", "-") / f"{sid}.jsonl"
    base = {"timestamp": ts, "cwd": cwd, "sessionId": sid, "version": "2.0.1"}
    tool_use = {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": command}}
    result = {"type": "tool_result", "tool_use_id": "toolu_1", "content": output}
    jsonl(
        path,
        [
            {**base, "type": "user", "origin": {"kind": "human"}, "message": {"role": "user", "content": user}},
            {
                **base,
                "type": "assistant",
                "apiBlockIndex": 0,
                "message": {"id": "msg_1", "role": "assistant", "stop_reason": "tool_use", "content": [tool_use]},
            },
            {**base, "type": "user", "message": {"role": "user", "content": [result]}},
            {
                **base,
                "type": "assistant",
                "apiBlockIndex": 0,
                "message": {
                    "id": "msg_2",
                    "role": "assistant",
                    "stop_reason": "end_turn",
                    "content": [{"type": "text", "text": answer}],
                },
            },
        ],
    )


def copilot_session(world, sid, ts, cwd, user, command, output, answer):
    def ev(typ, data):
        return {"type": typ, "data": data, "id": f"{typ}-{sid[:4]}", "timestamp": ts, "parentId": None}

    start = {"sessionId": sid, "producer": "copilot-agent", "copilotVersion": "1.0.103", "context": {"cwd": cwd}}
    jsonl(
        world / f"agents/copilot/session-state/{sid}/events.jsonl",
        [
            ev("session.start", start),
            ev("user.message", {"content": user, "attachments": []}),
            ev("tool.execution_start", {"toolCallId": "t1", "toolName": "bash", "arguments": {"command": command}}),
            ev("tool.execution_complete", {"toolCallId": "t1", "result": {"content": output}}),
            ev("assistant.message", {"content": answer}),
        ],
    )


def first_sessions(world, bs):
    raw, labels = bs / "data/raw/2026-03-field", bs / "data/labels"
    codex_session(
        world,
        CODEX_1,
        "2026-03-02T09:14:00.000Z",
        str(bs),
        "Where are the March field recordings? I want to start a species classifier.",
        f"ls {raw} && head -3 {labels}/v1/labels.csv",
        f"site_a\nsite_b\n{labels}/v1/labels.csv: clip,species",
        f"The March recordings are in `{raw}`, one folder per site (16 kHz mono WAV). Labels are in "
        f"`{labels}/v1/labels.csv`. Note: site_b clips 40-80 look mislabeled (wren vs. robin), so check them "
        "before training.",
    )
    claude_session(
        world,
        CLAUDE_1,
        "2026-03-09T14:30:00.000Z",
        str(bs),
        "Relabel site_b, then train the CNN baseline on the fixed labels.",
        f"python train.py --labels {labels}/v2/labels.csv --out {bs}/experiments/exp012_cnn_baseline",
        "macro_f1=0.71",
        f"Relabelled site_b into `{labels}/v2/labels.csv` (v1 is superseded and removed). The CNN baseline in "
        f"`{bs}/experiments/exp012_cnn_baseline` reaches macro-F1 0.71 on a random split.",
    )
    copilot_session(
        world,
        COPILOT_1,
        "2026-03-15T11:05:00.000Z",
        str(bs),
        "Fine-tune BEATs and compare with the baseline. Use a split that doesn't leak sites.",
        f"python finetune.py --split {bs}/data/splits/site_folds.json --out {bs}/experiments/exp013_beats_finetune",
        "macro_f1=0.78",
        f"BEATs fine-tuning (`{bs}/experiments/exp013_beats_finetune`) reaches macro-F1 0.78 with the "
        f"leave-one-site-out split in `{bs}/data/splits/site_folds.json`. The baseline's 0.71 used a random split, "
        "so it is optimistic; rerun it on the site split before comparing.",
    )
    jsonl(
        world / "agents/codex/session_index.jsonl",
        [{"id": CODEX_1, "thread_name": "Find March field recordings", "updated_at": "2026-03-02T09:20:00Z"}],
    )


def later_session(world, bs):
    """The project moves on: the raw recordings move to the archive share."""
    src, dst = bs / "data/raw/2026-03-field", world / "archive/birdsong/2026-03-field"
    dst.parent.mkdir(parents=True)
    shutil.move(src, dst)
    codex_session(
        world,
        CODEX_2,
        "2026-03-20T16:40:00.000Z",
        str(bs),
        "The repo disk is full. Move the March raw recordings to the archive share.",
        f"mv {src} {dst}",
        "",
        f"Moved the March recordings to `{dst}`. `{src}` no longer exists; update loaders that point there.",
    )


# --- the atlas home ---------------------------------------------------------------------------------------------


def write_config(world, home, bs):
    agents = world / "agents"
    config = f"""\
[sources]
codex_sessions = "{agents}/codex/sessions"
codex_session_index = "{agents}/codex/session_index.jsonl"
claude_projects = "{agents}/claude/projects"

[sources.copilot]
agent_state = "{agents}/copilot/session-state"

[project]
name = "birdsong"
work_dir = "work/birdsong"
knowledge_dir = "projects/birdsong/knowledge"
roots = ["{bs}"]
cwd_also = []
exclude_cwd = ["{home}"]
exclude_ids = []

[paths]
roots = ["{world}/research", "{world}/archive"]
verify_timeout_s = 5
max_session_ids = 20

[limits]
user_text = 8000
agent_final = 40000
agent_commentary = 2000
tool_input = 400
subagent_result = 3000

[knowledge]
abbreviations = {{ BS = "{bs}", ARCH = "{world}/archive" }}
new_path_min_sessions = 1
"""
    home.mkdir(parents=True)
    (home / "config.toml").write_text(config, encoding="utf-8")


def install_knowledge(home):
    """Stand-in for step 3 of docs/refresh-guide.md, where a coding agent writes the cited knowledge files."""
    dest = home / "projects/birdsong/knowledge"
    dest.mkdir(parents=True)
    for md in sorted((HERE / "knowledge").glob("*.md")):
        shutil.copy(md, dest / md.name)
    return dest


def run(home, *argv, stdout=None):
    shown = " ".join(argv) + (f" > {stdout.relative_to(home)}" if stdout else "")
    print(f"\n$ researchatlas {shown}", flush=True)
    with open(stdout, "w", encoding="utf-8") if stdout else contextlib.nullcontext(sys.stdout) as out:
        with contextlib.redirect_stdout(out):
            code = atlas(["--config", str(home / "config.toml"), *argv])
    if code:
        raise SystemExit(f"researchatlas {argv[0]} exited with {code}")


def heading(text):
    print(f"\n{'=' * 100}\n{text}\n{'=' * 100}", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", help="folder for the demo world (default: a temporary folder, removed afterwards)")
    args = ap.parse_args()
    if args.dir:
        world = Path(args.dir).resolve()
        if world.exists():
            raise SystemExit(f"{world} already exists; pass a new folder")
        world.mkdir(parents=True)
        tmp = None
    else:
        tmp = tempfile.TemporaryDirectory(prefix="atlas-demo-")
        world = Path(tmp.name).resolve()
    try:
        home = world / "atlas"
        bs = build_project(world)
        first_sessions(world, bs)
        write_config(world, home, bs)

        heading("1. Index three past sessions (Codex, Claude Code, Copilot) and verify every path they mention")
        run(home, "extract")
        run(home, "paths")

        heading("2. Write the cited knowledge base, then record the sessions it covers as reviewed")
        kdir = install_knowledge(home)
        print(
            f"\n(agent step) wrote {', '.join(p.name for p in sorted(kdir.glob('*.md')))} in {kdir.relative_to(home)}"
        )
        report = home / "work/birdsong/refresh_20260316.txt"
        run(home, "refresh", stdout=report)
        run(home, "mark-reviewed", "--report", str(report), "--note", "initial knowledge base")

        heading("3. A new agent session asks where the labels are")
        run(home, "find", "labels")

        heading("4. A week later: the raw recordings move to the archive share, and a new session records it")
        later_session(world, bs)
        run(home, "refresh")
        print(f"\nDemo world: {world if args.dir else '(temporary, removed)'}")
    finally:
        if tmp:
            tmp.cleanup()


if __name__ == "__main__":
    main()
