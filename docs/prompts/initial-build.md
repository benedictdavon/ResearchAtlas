# Initial build prompt (the first knowledge base)

Used for step 4 of [getting-started.md](../getting-started.md). The user saves a refresh report, starts an agent in
the atlas home and says: "Follow `initial-build.md` with the report `work/<project>/refresh_<YYYYMMDD>.txt`."

Below, `<project>` is `[project].name` from `config.toml`, the knowledge folder is `projects/<project>/knowledge/`,
the condensed transcripts are in `work/<project>/sessions/`, and `<prompts>` is the folder holding this file.

---

You are building the first ResearchAtlas knowledge base for a research project from its past coding-agent
sessions. Future agents will read it to find datasets, paths and research history without asking the user.

**Read first:** `config.toml` (project roots, path abbreviations), the refresh report named by the user, and
`work/<project>/sessions.jsonl` (one line per session: `source`, `short_id`, `parent_id`, `cwd`, `start`, `title`,
`condensed_path`).

**Rules**
- Read-only outside the atlas home. Never modify the research repo, data mounts, related repos or databases. Read
  other branches of a repo with `git show` / `git log`, never by checking them out.
- Sessions are leads, not truth: past agents guessed, stopped mid-run and were sometimes wrong. Prefer what the
  filesystem and the experiment folders' own files (README, results, logs) show.
- Check every path you write on disk with a timeout (`timeout 10 ls -d <path>`); network mounts can hang. Mark it
  `✓ <today>`, or `✗ <today>` if it is gone but worth knowing about. Never construct or guess a path.
- Cite every claim: `[codex:<id13> <date>]`, `[claude:<id8> <date>]`, `[copilot:<id8> <date>]` (the short id from
  the condensed file's header and the date of the message that says it) or `[file:<path>]`.
- When sources conflict, higher rank wins, and within a rank the newer one: (1) the filesystem or project database,
  (2) recent sessions and the experiment folders' own files, (3) handoff or summary documents in the research repo,
  (4) older sessions, (5) documents known to be outdated. Material conflicts go to `open_questions.md` §3.
- Never invent paths, numbers or conclusions. Copy numbers exactly. If unsure, write an open question.

**Steps**
1. **Plan.** Group the sessions by research topic, usually the experiment folder of the session's `cwd`. Keep a
   session together with its subagents and forks (`parent_id`). Measure the condensed text per group (`wc -c`).
   Ask the user which datasets or topics matter most, and cover those first and in full depth.
2. **Read the sessions.**
   - **Small project** (≤ ~10 sessions and ≤ ~400 KB in total): read every condensed file yourself, completely.
   - **Larger project:** pack the groups into batches of ≤ ~400 KB without splitting a group. Give each batch to a
     subagent with `<prompts>/claim-extraction.md`, naming the batch and its condensed files in the task. Each
     writes cited candidate claims to `work/<project>/claims/<batch>.md`. With many batches, have subagents merge
     the claims of one research track each with `<prompts>/digest.md` into `work/<project>/digests/<track>.md`.
3. **Read the primary sources.** The research repo's handoff or summary documents, and for each experiment that
   matters its folder's README and results files. Note datasets they mention that no session covered.
4. **Write the knowledge files** in `projects/<project>/knowledge/`, in this format:
   - `datasets.md`: one `##` section per logical dataset: name and aliases, type, verified paths with roles (raw
     data, references, labels, configs), database tables if any, caveats, sources.
   - `experiments.md`: one `###` entry per experiment that matters: status first (current / superseded by X /
     abandoned / in progress), then purpose, data, method, result with key numbers, sources. With several research
     tracks, make `experiments.md` a hub (conventions, authoritative logs, index) and put the entries in
     `experiments_<track>.md` files.
   - `decisions.md`: accepted and rejected hypotheses, baselines and rules, dated. Keep superseded ones, marked.
   - `recipes.md` (optional): short loaders for the main datasets. Run each code block read-only before adding it,
     and say which interpreter it needs. Add nothing untested.
   - `open_questions.md`: §1 questions for the user, §3 conflicts between sources.
   - `INDEX.md`, written last, ≤ ~60 lines: what each file holds, the main datasets at a glance, path
     abbreviations, how to search (`researchatlas find <words>`, `grep -n`), and when to run `researchatlas
     refresh`.

   Use path abbreviations from `[knowledge].abbreviations` for long prefixes. One entry per dataset or experiment;
   when a newer result replaces an older one, keep both and mark the old one superseded, with date and reason.
5. **Verify.**
   - `researchatlas refresh > work/<project>/check.txt` (it changes no review state). Its "Cited paths no longer
     OK" must be 0, or only paths you marked `✗`.
   - Spot-check `researchatlas find <topic>` for the main datasets.
6. **Report to the user:** what the knowledge base covers, the main datasets, conflicts you resolved and how,
   the questions in `open_questions.md` §1, and sessions you skipped and why. Apply the user's answers.
7. **Mark reviewed:** `researchatlas mark-reviewed --report <the report the user named>`. If you couldn't cover
   some sessions, mark only the finished ones by id (`mark-reviewed --report <report> <id> … --note "…"`) and say
   so. Sessions that grew during your work stay pending for the next refresh; that is intended.
