# Digest prompt (subagent, one research track)

Used by [initial-build.md](initial-build.md) when there are many claim batches. The orchestrating agent gives each
subagent this file, a track name and the claim files (`work/<project>/claims/<batch>.md`) that belong to the
track. It then writes the knowledge files from the digests, checking key items against the sources.

---

You are merging extracted research claims for one research track into a digest. Read every claim file you are
given, completely. Claims are bullets of the form
`- <claim> | paths: … | who: USER|AGENT|SUBAGENT | #tags | [<source>:<short id> <date>] …`.

When claims conflict, higher rank wins, and within a rank the newer one: (1) facts verified on disk, (2) recent
sessions and the experiment folders' own files, (3) handoff or summary documents, (4) older sessions. Among
sessions, prefer what the USER stated or an agent verified over agent plans.

Write `work/<project>/digests/<track>.md` (at most ~25 KB) with exactly these sections:

## EXPERIMENTS
One block per experiment (an experiment folder, or a named sub-experiment), in chronological order:

```
### <experiment id or name> — <folder, if known>
- purpose: …
- data: <datasets used>; key paths (copied exactly, with the ✓/✗/? marks from the claims)
- method: <one or two lines>
- result: <key numbers exactly as in the claims>
- status: current | superseded by <X> | partial | rejected | in progress (as of <date>)
- sources: [<source>:<short id> <date>] [file:…]
```

Merge duplicates across claim files and keep their citations (at most 4 per block).

## DECISIONS
One bullet per accepted or rejected hypothesis, baseline or rule:
`- <date> — <decision> — status: current | superseded by <date/decision> — [citations]`.
Mark later reversals explicitly.

## CONFLICTS AND OPEN
One bullet per unresolved conflict (both versions, with citations) or open question that matters for using the
data or interpreting results. Skip trivia such as process ids or line-number drift.

Never invent anything; copy numbers and paths exactly; keep the citations. Don't edit any other file. Finish with
a report of at most 8 lines: the block, decision and open counts, and the most important conflicts.
