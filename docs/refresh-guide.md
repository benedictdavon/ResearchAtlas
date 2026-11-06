# Refreshing the atlas after new sessions

Use this after new research work (Codex, Claude Code or GitHub Copilot sessions) so the atlas knows about it.
The `researchatlas` CLI does the mechanical part (indexing transcripts, checking paths). An agent does the understanding part
(updating the knowledge files). You review the result once.

Commands run in the atlas home (here `/home/user/.researchatlas`; see
[configuration.md](configuration.md#the-atlas-home)) with Python 3.11+. From a source checkout, `python atlas.py` works in place of `researchatlas`. Examples use
`demo_project` as the project name; substitute `[project].name` / `work_dir` from your `config.toml`.

## Steps

**0. Only if you use the VS Code Copilot Chat panel from a client PC: copy its sessions to the server** (D22, D24)

Chat-panel history lives on the client machine (`%APPDATA%\Code\User\workspaceStorage\<hash>\chatSessions\` on
Windows). A remote VS Code Server may keep a copy only until its container restarts.

### Automated upload (`tools/copilot_sync.py`)

The uploader uses an existing outbound SSH connection from the client to the server. No client-side SSH server,
administrator rights or inbound port is needed. Requirements on the client: Python 3.9+ and `ssh`/`scp` with your
normal SSH authentication. Never put passwords or keys into config files or scripts.

On the client (PowerShell shown), fetch the standalone script from the repository and **preview first**:
```powershell
curl.exe -LO https://raw.githubusercontent.com/benedictdavon/ResearchAtlas/main/tools/copilot_sync.py
py -3 .\copilot_sync.py --root /home/user/research/demo_project
```
The preview scans `<workspaceStorage>\*\workspace.json` for workspaces whose folder equals or lies under a `--root`
(the remote path of the folder as VS Code opened it) and prints each selected workspace, its log count and the
uncompressed size. **Preview makes no copies, network connections or filesystem changes.**

- Repeat `--root` for each folder to include. `/` is refused.
- Multi-root workspaces and workspaces without a single folder are warned about and skipped.
- VS Code Insiders or custom profiles: pass `--storage <path to workspaceStorage>`.

If the preview is right, upload:
```powershell
py -3 .\copilot_sync.py --root /home/user/research/demo_project --upload `
    --host <user>@<server> --port <port> --atlas-dir /home/user/.researchatlas
```
(`--atlas-dir` is the server's atlas home, the folder holding `config.toml`. `--remote-python` is a server Python
that can import `atlaslib`, e.g. the venv where you installed ResearchAtlas; default `/usr/bin/python3`.) The script:
- reads files that VS Code keeps open with shared read/write/delete access; a log that keeps changing during three
  copy attempts fails explicitly (retry when the session is idle);
- bundles only `workspace.json` folder mappings and `chatSessions/*.jsonl` (no edit snapshots, caches, databases or
  credential files);
- copies the ZIP with `scp` into `<atlas-dir>/work/`, then runs `python -m atlaslib import-copilot <archive> --extract` in the atlas home over
  `ssh`, and removes the remote archive afterwards (a cleanup failure is reported);
- on the server, `import-copilot` validates entry names, file types and workspace selection, installs into
  `work/copilot_import/workspaceStorage/` atomically, keeps unchanged files' mtimes and retains older logs.

Each run uploads a full snapshot of the selected logs; unchanged files are not rewritten or re-condensed. A synced
chat overrides an older manual copy of the same session UUID (D24). The upload does not update knowledge or the
review ledger; continue at step 1.

### Manual fallback

Copy the workspace's `chatSessions\*.jsonl` files (with shared read access, since VS Code keeps them open), move them
to the server, and add a `[sources.copilot].chat_dirs` entry `{ path = "<dir>", cwd = "<workspace folder>" }`.
Once a session is in the synced mirror, use the uploader for its updates (the mirror takes precedence).

Copilot agent sessions (`~/.copilot/session-state`) already live on the machine where the agent ran and need no
step, as long as `agent_state` points there.

**1. Index the new sessions**
```bash
cd /home/user/.researchatlas
researchatlas refresh | tee work/demo_project/refresh_$(date +%Y%m%d).txt
```
This condenses new transcripts into `work/demo_project/sessions/`, re-checks every path cited in the knowledge files
and saves the report. It never marks anything as done: sessions stay listed until step 5 (D25).

**2. Read the report.** It has these parts:
- **New sessions (not reviewed)** and **Changed since review**, with titles: what needs writing up. "Changed" means a
  session already written up has grown or changed (it was still running, or was resumed).
- **Atlas feedback in these sessions**: lines where an agent that used the atlas said it was wrong or stale. Fix these
  first.
- **Cited paths no longer OK**: data the atlas points to that has moved or been deleted. These must be fixed.
- **New paths not yet in knowledge/**: candidates to add if they matter (most don't).

If there are no new sessions and no broken paths, stop here.

**3. Have an agent update the knowledge files.** Start Claude Code, Codex or Copilot **in the atlas home** and
say:
> Follow `docs/prompts/incremental-update.md` with the report `work/demo_project/refresh_<YYYYMMDD>.txt`.

With a pip install, the prompt files aren't in the atlas home; point the agent at your downloaded copy instead
([getting-started.md](getting-started.md#4-build-the-first-knowledge-base)).

The agent reads the new sessions, checks the experiment folders' own result files (sessions are leads, not truth),
updates `datasets.md`, the `experiments_<track>.md` files, `recipes.md`, `decisions.md` and `open_questions.md` with
citations, marks superseded results, fixes broken paths, and puts anything it can't settle in `open_questions.md`.
With many sessions (more than ~10, or more than ~400 KB of condensed text) it splits them into batches for subagents.
Sessions started in the atlas home are never indexed (D16), so the update session doesn't count as research.

**4. Review** (your part, ~5–10 min)
- `git diff projects/` shows exactly what changed in the knowledge.
- New questions for you appear in `projects/demo_project/knowledge/open_questions.md` §1. Answer them in chat; the
  agent applies the answers.

**5. Mark the sessions as done** (the agent does this at the end of step 3; you can also run it)
```bash
researchatlas mark-reviewed --report work/demo_project/refresh_<YYYYMMDD>.txt
```
This records every session listed in that report in `projects/demo_project/reviewed_sessions.jsonl` with the
content hash the report printed. Sessions that started or changed after the report stay pending. To mark only some:
`researchatlas mark-reviewed --report <report> <id> … --note "why"`.

**6. Commit** (the agent can do this if you ask):
```bash
git add projects/ docs/ && git commit -m "Refresh: <topics> (<N> sessions, <date range>)"
```

## When something looks wrong

| Symptom | What to do |
|---|---|
| A cited path is reported missing | Find where it moved (new sessions, `timeout 10 ls`), then fix it or mark it `✗ <date>` in the knowledge file. Never "fix" the data itself |
| `refresh` hangs | A network mount is unresponsive. Interrupt and retry later. Path checks have timeouts, but listing a dead mount can still stall |
| `atlaslib/` was edited | Run `python -m unittest discover -s tests` |
| A session shouldn't be in the atlas (a test, a probe) | Add its id prefix to `[project].exclude_ids` in `config.toml` (D20) and re-run step 1 |
| Every session shows as "changed" | Condensed transcripts were regenerated (e.g. after an extractor change), so all hashes moved. Check a few diffs, then re-baseline with `mark-reviewed --report` |
| A session you skipped keeps reappearing | Mark it with a note: `mark-reviewed --report <report> <id> --note "no research content"` |
| `import-copilot` refuses the archive | Check that `chat_storage` is `work/copilot_import/workspaceStorage` (relative to the atlas home) and that the workspace folder lies under `[project].roots` / `cwd_also` |

## How often

- After a session that produced results or moved data: the same day, so the atlas doesn't go stale. A finished
  experiment can otherwise remain listed as "in progress".
- Otherwise weekly is enough. Cited paths are re-checked on every run, so missing data shows up even without new
  sessions.
