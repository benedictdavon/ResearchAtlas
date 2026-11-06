# Incremental update prompt (after `researchatlas refresh`)

Used for step 3 of [refresh-guide.md](../refresh-guide.md). The user starts an agent in the atlas home and says:
"Follow `incremental-update.md` with the report `work/<project>/refresh_<YYYYMMDD>.txt`."

Below, `<project>` is `[project].name` from `config.toml`, the knowledge folder is `projects/<project>/knowledge/`,
the condensed transcripts are in `work/<project>/sessions/`, and `<prompts>` is the folder holding this file.

---

You are updating the ResearchAtlas knowledge files from a refresh report.

**Read first:** `projects/<project>/knowledge/INDEX.md` and the refresh report named by the user. Open the other
knowledge files when you need them.

**Rules**
- Read-only outside the atlas home. Never modify the research repo, data mounts, related repos or databases, even to
  "fix" a path.
- Sessions are leads, not truth. When a session reports a result, check the experiment folder's own files.
  - Typical files: `README.md`, `RESULTS.md`, `FINDINGS.md`, `REPORT.md`, experiment logs, result JSON files.
  - **The file wins.** Sessions often stop mid-run; the folder shows the final state.
- Check every path you add on disk with a timeout (`timeout 10 ls -d …`). Mark it `✓ <today>`. Write nothing you
  couldn't verify as a path.
- Cite every claim: `[codex:<id13> <date>]`, `[claude:<id8> <date>]`, `[copilot:<id8> <date>]`, or `[file:<path>]`.
  The condensed transcript for a citation is `work/<project>/sessions/<source>_<id>.md`.
- When sources conflict, higher rank wins, and within a rank the newer one: (1) the filesystem or project
  database, (2) recent sessions and the experiment folders' own files, (3) handoff or summary documents in the
  research repo, (4) older sessions, (5) documents known to be outdated.
- Never invent paths, numbers or conclusions. If something is unclear or two sources conflict, add it to
  `open_questions.md` (§1 for questions to the user, §3 for result conflicts) instead of guessing.
- Keep the existing style of each file: path abbreviations from `[knowledge].abbreviations` (e.g. `DP/`), section
  structure, ≤ ~60 lines for `INDEX.md`.

**Steps**
0. **Atlas feedback first.** The report's "Atlas feedback" section lists lines where an agent that used the atlas
   corrected it. Check each against the files and fix the knowledge (cite the session). False positives are possible.
1. **List the work.** From the report, take the new and changed sessions. Group them by experiment folder (the `cwd`
   in each condensed file's header). Keep a parent and its subagents/forks together.
   - **Small** (≤ ~10 sessions and ≤ ~400 KB condensed in total, `wc -c`): read them yourself, completely.
   - **Large:** pack the groups into batches of ≤ ~400 KB and give each batch to a subagent with
     `<prompts>/claim-extraction.md`, naming the batch `<YYYYMMDD>_<group>` and its condensed files in the task. It
     writes cited claims to `work/<project>/claims/<batch>.md`. Then merge the claims yourself.
2. **Check against the files.** For each experiment touched, open its folder and its results files. Note the status
   (complete / in progress / abandoned), the conclusion, and the key numbers with their source file.
3. **Update the knowledge files.**
   - `experiments_<track>.md` (`experiments.md` is only the hub and index): update the experiment's one `###` entry
     (purpose, data, method, result, status, sources), or add one if it is new. Put the current status first. When a
     result replaces an earlier one, keep the old one and mark it **superseded** (with date and by what). Don't
     delete it, and don't add a second entry for the same experiment. Add a new track file only for a new research
     line, and list it in the hub and `INDEX.md`.
   - `recipes.md`: only if a loading convention changed. Run any changed code block read-only before saving it.
   - `decisions.md`: new or changed decisions, dated. Update any "current status" summary if a headline changed.
   - `datasets.md`: new datasets, new recordings of an existing dataset, moved paths, new caveats.
   - `open_questions.md`: new conflicts and questions. Remove or resolve ones the new evidence settles, saying how.
   - `INDEX.md`: only if a top dataset or a key convention changed.
4. **Fix broken cited paths** from the report. Find where the data went (new sessions, `timeout 10 ls`). Update the
   path, or mark it `✗ <today>` with a note if it's really gone.
5. **New uncited paths** from the report: add only those that belong to a dataset or experiment you're documenting.
   Ignore caches, `__pycache__`, scratch files.
6. **Verify.**
   - Run `researchatlas refresh > work/<project>/check.txt` (it changes no review state). "Cited paths no longer
     OK" must be 0, or only paths you marked `✗`.
   - Spot-check with `researchatlas find <new topic>`.
7. **Report to the user.**
   - Sessions covered, by topic. The main knowledge changes, especially superseded results.
   - Paths fixed. Questions added.
   - Sessions you skipped and why (e.g. no research content).
   - Commit only when asked.
8. **Mark reviewed.** `researchatlas mark-reviewed --report <the report>`. Sessions you skipped on purpose are
   marked too; say so in your report. If you could not finish some, mark only the finished ones by id
   (`mark-reviewed --report <report> <id> … --note "…"`). Always mark against the supplied report, even if sessions
   grew during your work: their newer content then stays pending for the next refresh.
