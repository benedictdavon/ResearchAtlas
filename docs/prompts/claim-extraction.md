# Claim-extraction prompt (subagent, one batch of sessions)

Used by [initial-build.md](initial-build.md) and [incremental-update.md](incremental-update.md) for larger
projects. The orchestrating agent gives each subagent this file, a batch name and the list of condensed files in
the batch, and later merges the claims into the knowledge files.

---

You are extracting cited research claims from condensed coding-agent sessions, for a knowledge base that future
agents use to find and use research data without asking the user.

**Input:** the condensed transcripts named in your task, under `work/<project>/sessions/`. Read every file
completely, in order; read big files in parts, and never skip one. Each file starts with a header
(`# <source>:<short id> — <title>`, then kind, parent, cwd, start). Sections are `### <YYYY-MM-DD HH:MM> <LABEL>`
with labels such as USER, AGENT, AGENT (final), TASK (from parent), SUBAGENT RESULT, SUBAGENT REPORT, RECAP.
Bullets starting `- $` are shell commands the agent ran; their outputs are not included.

**Output:** `work/<project>/claims/<batch>.md`. Write nothing else, anywhere. Don't edit the knowledge files.
Read-only outside the atlas home.

**What to extract:**
1. **DATASET:** a logical dataset: name and aliases, type, subjects or sources, devices, dates, and **absolute
   paths with their role** (raw data, reference, labels, manifest, database import, cache, results). Database
   tables or queries when stated.
2. **CAVEAT:** anything that limits how data may be used: alignment or sync status, missing or truncated
   recordings, unreadable files, label problems, development vs. held-out data, "not ground truth", time zones.
3. **EXPERIMENT:** experiment folder, purpose, data used, method, result with key numbers, status.
4. **DECISION:** an accepted or rejected hypothesis, baseline choice or rule, with its date. If a later session
   reverses an earlier conclusion, also write a **SUPERSEDED** claim naming both.
5. **CODE:** the authoritative loader, module or notebook for a dataset or method: path and what it does.
6. **OPEN:** an unresolved question, a conflict between sessions, or something the agent couldn't confirm.

If your task names priority topics, extract those in full depth and tag them. Tag the rest by topic (`#<topic>`).

**Claim format:** one claim per bullet, grouped under `## DATASET`, `## CAVEAT`, `## EXPERIMENT`, `## DECISION`,
`## SUPERSEDED`, `## CODE`, `## OPEN`:

```
- <one or two specific sentences, with numbers, dates and names as stated> | paths: `<abs path>` (<role>); … | who: USER|AGENT|SUBAGENT | #tags | [<source>:<short id> YYYY-MM-DD]
```

- **Citation:** the short id from the file header and the date of the *section* where the claim appears, not the
  session start. Cite several sessions if several state the same thing.
- **who:** USER if the user's own message states it (most authoritative for intent, naming and what the data is);
  AGENT or SUBAGENT if an agent concluded it. Prefer facts the agent *verified* (after listing or loading files)
  over plans and guesses. Add "(planned)" or "(unverified)" to intentions and guesses.
- **Paths:** copy them exactly; never construct or guess one. If only a relative path is given, join it with the
  session's cwd and add "(joined with cwd)". Look each path up in `work/<project>/paths.jsonl`
  (`grep -F '"path": "<path>"'`) and append its status: `✓exists`, `✗missing` or `?not-indexed`.
- Keep numbers exactly as stated; don't round or merge. Don't copy whole messages, routine tool chatter or
  session-management noise. Don't invent anything; if unsure, write it as OPEN.
- Aim for completeness on datasets, paths, caveats and decisions, and brevity elsewhere.

Start the file with:

```
# Claims: <batch>
- sessions: <short ids, in order>
- dates: <first>..<last>
- extracted: <today>
```

End it with `## NOTES`: what was hard to interpret, and which sessions had little content.

Finish with a report of at most 10 lines: the claim count per section, the most important findings, and anything
you were unsure about.
