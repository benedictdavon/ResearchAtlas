# Benchmark

Does pointing a coding agent at the atlas help, and what does it cost? This page reports a controlled comparison run
on 2026-11-02 on the research project ResearchAtlas was built for ([background.md](background.md)), and a
follow-up on 2026-11-06 with smaller models ([Smaller models](#smaller-models)). Design decision: D28.

## Summary

- **Fewer tokens, less time, same or better answers.** On 9 research questions, runs with the atlas pointer used
  **0.49×** (Claude Code) and **0.42×** (Codex) the tokens of runs without it, and finished in less than half the
  wall time. Pass rates rose from 19/26 to 26/27 (Claude Code) and from 13/15 to 14/15 (Codex).
- **Cheaper per correct answer.** Cost per passing answer fell from $0.50 to $0.24 (Claude Code) and from $0.44 to
  $0.24 (Codex).
- **No overhead when it isn't needed.** On control questions that don't need the atlas, the pointer changed token
  use by 0.96× and 1.00×.
- **Loading the whole knowledge base is the expensive option.** Telling the agent to read every knowledge file
  first gave similar quality at 1.6× (Claude Code) and 3.7× (Codex) the tokens.
- **A folder hint is no substitute.** A user-style hint about where to look left token use about the same and, for
  Codex, lowered the pass rate.
- **Smaller models gain more.** Rerun with Claude Haiku 5.5 and gpt-6-luna, the atlas raised pass rates from 17/27
  to 26/27 for both agents, at 0.55× and 0.37× the tokens. Cost per passing answer was $0.05 and $0.02.

The evidence comes from one project and 9 questions, so treat it as indicative ([limitations](#limitations)).

## Setup

### Questions

Eleven questions, written with their answer keys before any run. Facts in the answer keys were checked on disk.
The questions name the project's own datasets, so they are described here rather than published.

| Id | Category | What it asks | Rubric items | Critical errors |
|---|---|---|---|---|
| A1 | retrieval | Where one participant's data is: raw recordings and any reference measurements | 6 | 3 |
| A2 | retrieval | Where the reference-sensor recordings are, which raw sessions they pair with, and which pairings are validated | 7 | 2 |
| A3 | retrieval | Where the data recorded in a given month is, and its database import status | 5 | 2 |
| A4 | retrieval | A dataset known by a date nickname, and its reference recording. A mount path that sessions often mention doesn't exist | 4 | 2 |
| A5a | retrieval | Which experiments tested a preprocessing variant of a detector, and what was concluded | 4 | 2 |
| A5b | retrieval | Whether a reproduced published method is still the current baseline | 4 | 1 |
| A6 | negative | Where a dataset is that never existed. The correct answer says so and invents no path | 1 | 1 |
| T1 | task | Compute the median of a reference signal over one overnight recording, using only samples with good quality flags, and name the file | 2 | 2 |
| T2 | task | Count the 10-minute recording rounds of a given night and name the raw export folder | 2 | 2 |
| C1 | control | Which Python interpreter to use in the repo, and where a new experiment notebook goes | 2 | 1 |
| C2 | control | What arguments a function of the project's data-access library takes, and what it returns | 2 | 1 |

A1 to T2 need research history; C1 and C2 are answerable from the repository alone and measure the pointer's
overhead.

### Arms

Runs were identical except for the standing instructions the agent saw:

| Arm | Instructions |
|---|---|
| `none` | The research repo's own `AGENTS.md` without the atlas line; the atlas is hidden from the filesystem |
| `atlas` | The normal setup: a global pointer and the repo's pointer line ("read `INDEX.md` first; search with `find`") |
| `dump` | Like `none`, plus "read every file in the knowledge folder in full first" (256 KB at the time) |
| `hint` | Like `none`, plus a user-style folder hint after the question, such as where the experiment folders are (not the answer). Not used for C1 and C2 |

### Agents and runs

| | Claude Code | Codex |
|---|---|---|
| Version | 2.1.308 | codex-cli 0.164.0 |
| Model | Claude Opus 5.5 (1M context), effort high | gpt-6.1-sol, effort high |
| Subagents allowed | Claude Haiku 5.5 (none were spawned) | gpt-6-luna (none were spawned) |
| Repetitions | 3 for `none` and `atlas`, 2 for `dump` and `hint` | 1 complete, plus 23 runs of a second |
| Scored runs | 105 | 65 |

Each run was fresh, non-interactive and not persisted (so it could never become atlas evidence), started in the
research repo, with a 20-minute timeout. No run timed out. Unequal repetitions are fine because each question's
repetitions are averaged before arms are compared.

### Isolation

Every run executed in a [bubblewrap](https://github.com/containers/bubblewrap) mount namespace with a read-only view
of the whole filesystem; only `/tmp` and a private stage folder were writable.

- The on-disk instruction files (the repo's `AGENTS.md`, the global pointer files) were replaced by the arm's text.
- The benchmark itself, its answer keys and older test material were hidden in every arm; the atlas and the
  sessions that built it were hidden in `none` and `hint`.
- Codex got a private, empty `CODEX_HOME`, so its memory was empty and subagent rollouts could be counted. Claude
  Code got the arm text through `--append-system-prompt-file`, with the user's instruction files excluded; its
  project memory was visible read-only, the same in every arm.

Building this surfaced two things worth knowing beyond the benchmark:

- **Codex reads `AGENTS.md` from disk** even with `project_doc_max_bytes=0`: the setting only keeps the file out
  of the prompt, and the agent may still `cat` it and follow it. A "no instructions" baseline is contaminated unless
  the file itself is replaced.
- **Tool allowlists don't make an agent read-only.** In a pilot run before the sandbox, `claude -p` with an
  allowlisted Python interpreter wrote to the user's Claude memory file (reverted). Only the read-only filesystem
  prevented writes. That pilot was discarded, except for runs that touched none of the newly hidden paths.

More detail: [transcript-formats.md](transcript-formats.md#agent-isolation-for-benchmarks).

### Metrics and grading

- **Tokens** (primary): input, including cached input, plus output, over all models including subagents. This is
  independent of prices and caching discounts.
- **Cost:** Claude Code reports it per run, and it matched the billing. Codex reports none, so per-run cost was
  estimated from list prices and scaled to the billed total (see [Spend](#spend)).
- **Wall time**, tool calls, peak context, and every path in the answer checked on disk.
- **Quality:** answers were graded blind against the rubric: each item met or not, and a score of items met ÷
  items, or 0 if the answer made a listed critical error (such as presenting a non-existent path as the data's
  location). **Pass** means a score of at least 0.8. One LLM grader per question saw all answers to that question,
  anonymized and shuffled, and was told to ignore which sources an answer cited. The T1 and T2 answers were also
  checked mechanically against the ground truth, and low scores and the critical error were reviewed by hand.
- **Corrections after the run:** A3's database-status item was re-keyed to the database state on the run date,
  checked afterwards from file install times, and that item was regraded. One Claude Code `none` run of A6 is
  excluded: it found an old test plan that contained the expected answer.
- **Analysis:** for each question, the geometric mean over repetitions of arm ÷ `none`; then the geometric mean over
  questions, with a bootstrap 95% confidence interval that resamples questions, the independent unit.

## Results

### Research questions (A1 to T2)

| Agent | Arm | Runs | Pass | Mean score | Median tokens | Mean cost per run | Cost per pass | Median wall time |
|---|---|---|---|---|---|---|---|---|
| Claude Code | `none` | 26 | 19/26 | 0.86 | 369k | $0.36 | $0.50 | 102 s |
| Claude Code | **`atlas`** | 27 | **26/27** | **0.96** | **196k** | **$0.23** | **$0.24** | **45 s** |
| Claude Code | `dump` | 18 | 17/18 | 0.96 | 593k | $0.90 | $0.95 | 56 s |
| Claude Code | `hint` | 18 | 13/18 | 0.88 | 337k | $0.42 | $0.58 | 83 s |
| Codex | `none` | 15 | 13/15 | 0.92 | 239k | $0.38 | $0.44 | 90 s |
| Codex | **`atlas`** | 15 | **14/15** | **0.97** | **128k** | **$0.22** | **$0.24** | **54 s** |
| Codex | `dump` | 13 | 11/13 | 0.94 | 1,620k | $0.90 | $1.06 | 196 s |
| Codex | `hint` | 15 | 10/15 | 0.85 | 280k | $0.35 | $0.53 | 99 s |

Ratios to `none`, with 95% confidence intervals:

| Agent | Arm | Tokens | Cost | Wall time | Score difference |
|---|---|---|---|---|---|
| Claude Code | **`atlas`** | **0.49** (0.41–0.58) | **0.65** (0.56–0.75) | **0.41** (0.31–0.55) | +0.10 (−0.00 to +0.21) |
| Claude Code | `dump` | 1.57 (1.27–1.97) | 2.62 (2.21–3.15) | 0.47 (0.34–0.66) | +0.10 (−0.01 to +0.23) |
| Claude Code | `hint` | 1.05 (0.75–1.46) | 1.07 (0.84–1.35) | 0.73 (0.47–1.11) | +0.02 (−0.08 to +0.12) |
| Codex | **`atlas`** | **0.42** (0.34–0.53) | **0.59** (0.50–0.68) | **0.43** (0.36–0.52) | +0.02 (+0.00 to +0.07) |
| Codex | `dump` | 3.74 (1.96–6.73) | 2.35 (1.61–3.36) | 1.87 (1.11–2.71) | +0.02 (+0.00 to +0.07) |
| Codex | `hint` | 0.92 (0.73–1.22) | 0.98 (0.84–1.17) | 0.99 (0.81–1.16) | −0.08 (−0.17 to +0.00) |

Cost falls less than tokens because the atlas saves disproportionately on cached input, the cheapest kind: cached
input was 90% of Claude Code's `none` tokens but 84% of its `atlas` tokens (Codex: 85% and 76%). The median peak
context was 46k tokens with the atlas and 155k with `dump` (Claude Code).

### Per question

Median tokens (thousands) / mean score:

| Question | Claude `none` | Claude `atlas` | Claude `dump` | Claude `hint` | Codex `none` | Codex `atlas` | Codex `dump` | Codex `hint` |
|---|---|---|---|---|---|---|---|---|
| A1 retrieval | 557 / 0.61 | 194 / 0.89 | 594 / 1.00 | 914 / 0.75 | 581 / 1.00 | 186 / 1.00 | 1620 / 1.00 | 394 / 0.83 |
| A2 retrieval | 615 / 1.00 | 187 / 1.00 | 512 / 1.00 | 1063 / 1.00 | 891 / 1.00 | 211 / 1.00 | 1621 / 1.00 | 723 / 0.86 |
| A3 retrieval | 365 / 0.47 | 205 / 0.80 | 1027 / 0.80 | 708 / 0.40 | 159 / 0.40 | 81 / 0.60 | 866 / 0.60 | 200 / 0.50 |
| A4 retrieval | 667 / 0.67 | 198 / 1.00 | 934 / 1.00 | 807 / 1.00 | 266 / 1.00 | 90 / 1.00 | 1725 / 1.00 | 321 / 0.88 |
| A5a retrieval | 367 / 1.00 | 216 / 1.00 | 533 / 1.00 | 208 / 0.75 | 381 / 1.00 | 189 / 1.00 | 786 / 1.00 | 278 / 1.00 |
| A5b retrieval | 362 / 1.00 | 222 / 0.92 | 607 / 0.88 | 320 / 1.00 | 166 / 1.00 | 110 / 1.00 | 2177 / 1.00 | 377 / 0.62 |
| A6 negative | 329 / 1.00 | 119 / 1.00 | 787 / 1.00 | 191 / 1.00 | 479 / 1.00 | 149 / 1.00 | 268 / 1.00 | 292 / 1.00 |
| T1 task | 388 / 1.00 | 253 / 1.00 | 586 / 1.00 | 231 / 1.00 | 184 / 1.00 | 127 / 1.00 | 2054 / 1.00 | 118 / 1.00 |
| T2 task | 244 / 1.00 | 185 / 1.00 | 434 / 1.00 | 333 / 1.00 | 140 / 1.00 | 80 / 1.00 | 1185 / 1.00 | 129 / 1.00 |

The atlas used fewer tokens than `none` on every question, for both agents. The quality gains are in questions that
need research history rather than a file search: A1 (which datasets and references exist), A3 (which recordings
exist) and A4, where one Claude Code `none` run presented the non-existent mount path as
real.

### Control questions (C1, C2)

| Agent | Arm | Tokens × `none` | Cost × `none` |
|---|---|---|---|
| Claude Code | `atlas` | 0.96 (0.91–1.01) | 0.85 (0.73–0.98) |
| Claude Code | `dump` | 0.97 (0.93–1.01) | 0.93 (0.89–0.97) |
| Codex | `atlas` | 1.00 (0.97–1.02) | 1.02 (0.99–1.05) |
| Codex | `dump` | 2.46 (1.02–5.95) | 1.86 (1.06–3.29) |

All control runs passed. Claude Code's `dump` runs didn't open the knowledge files for these questions; Codex
skipped them on C1 but read them all on C2 (472k tokens instead of 79k).

## Smaller models

Coding agents often hand implementation work to a cheaper model. On 2026-11-06 the `none` and `atlas` arms were
rerun with two such models to see whether the atlas still helps when the agent itself is weaker.

### What changed

| | Claude Code | Codex |
|---|---|---|
| Version | 2.1.308 | codex-cli 0.166.0 |
| Model | Claude Haiku 5.5, effort high | gpt-6-luna, effort max |
| Repetitions | 3 for `none` and `atlas` | 3 for `none` and `atlas` |
| Scored runs | 66 | 66 |

- Same questions, sandbox, metrics and grading protocol, with a fresh set of blind graders. No run timed out,
  spawned a subagent or made a critical error.
- The knowledge base had grown to 332 KB through regular refreshes (256 KB on 2026-11-02).
- A3's database-status item is keyed to the database as of 2026-11-06, after a labeled import on 2026-11-05.
- Claude Code's paste cache (`~/.claude/paste-cache/`) and a new notes folder that quotes the atlas were also
  hidden in every arm.

### Results

Research questions (A1 to T2). Claude Code costs are computed from tokens at billed prices; Codex costs are
list-price estimates scaled to the bill (see [Spend](#spend)).

| Agent | Arm | Runs | Pass | Mean score | Median tokens | Mean cost per run | Cost per pass | Median wall time |
|---|---|---|---|---|---|---|---|---|
| Claude Code | `none` | 27 | 17/27 | 0.79 | 507k | $0.080 | $0.127 | 115 s |
| Claude Code | **`atlas`** | 27 | **26/27** | **0.96** | **295k** | **$0.049** | **$0.051** | **74 s** |
| Codex | `none` | 27 | 17/27 | 0.81 | 421k | $0.046 | $0.073 | 176 s |
| Codex | **`atlas`** | 27 | **26/27** | **0.95** | **157k** | **$0.018** | **$0.019** | **89 s** |

Relative to `none` (geometric mean over questions, bootstrap 95% CI):

| Agent | Tokens | Cost | Wall time | Score difference |
|---|---|---|---|---|
| Claude Code | **0.55** (0.42–0.71) | **0.63** (0.50–0.77) | **0.58** (0.43–0.79) | +0.17 (+0.03 to +0.33) |
| Codex | **0.37** (0.26–0.51) | **0.48** (0.37–0.60) | **0.52** (0.39–0.67) | +0.14 (+0.05 to +0.23) |

Median tokens (thousands) / mean score:

| Question | Claude `none` | Claude `atlas` | Codex `none` | Codex `atlas` |
|---|---|---|---|---|
| A1 retrieval | 517 / 0.44 | 399 / 0.89 | 683 / 0.67 | 229 / 1.00 |
| A2 retrieval | 942 / 0.52 | 203 / 1.00 | 1566 / 0.86 | 228 / 1.00 |
| A3 retrieval | 244 / 0.33 | 99 / 0.87 | 113 / 0.20 | 95 / 0.53 |
| A4 retrieval | 807 / 0.83 | 329 / 1.00 | 333 / 0.83 | 165 / 1.00 |
| A5a retrieval | 442 / 1.00 | 178 / 1.00 | 1082 / 1.00 | 276 / 1.00 |
| A5b retrieval | 345 / 1.00 | 412 / 0.92 | 281 / 0.75 | 109 / 1.00 |
| A6 negative | 585 / 1.00 | 329 / 1.00 | 433 / 1.00 | 136 / 1.00 |
| T1 task | 292 / 1.00 | 282 / 1.00 | 270 / 1.00 | 141 / 1.00 |
| T2 task | 557 / 1.00 | 263 / 1.00 | 244 / 1.00 | 96 / 1.00 |

- **The quality gain is larger than with the frontier models**, and both confidence intervals exclude zero. Without
  the atlas the smaller models missed more of the research history (A1 to A4); with it they passed about as often
  as the frontier models did.
- **Token savings are similar** (0.55× and 0.37×, against 0.49× and 0.42×). The atlas used fewer tokens on every
  question except Claude Code's A5b.
- **The weakest cell is Codex `atlas` on A3** (0.53): two answers left out how the month's recordings differ from
  earlier ones, and one named only the parent export folder.
- **Controls:** all 24 control runs passed. Tokens with the pointer were 0.94× (0.86–1.02) for Claude Code and
  1.04× (1.01–1.06) for Codex, a small overhead on base sizes of 13k (C1) and 70k (C2) tokens.

### Across model tiers

Pass rate and cost per pass on the research questions:

| Agent | Model | `none` | `atlas` |
|---|---|---|---|
| Claude Code | Claude Opus 5.5 | 19/26, $0.50 | 26/27, $0.24 |
| Claude Code | Claude Haiku 5.5 | 17/27, $0.13 | 26/27, $0.05 |
| Codex | gpt-6.1-sol | 13/15, $0.44 | 14/15, $0.24 |
| Codex | gpt-6-luna | 17/27, $0.07 | 26/27, $0.02 |

With the atlas, the smaller models passed about as often as the frontier models did with it, at a fifth (Claude
Code) and a twelfth (Codex) of the cost per pass, and more often than the frontier models without it. Read this
comparison loosely: the runs are four days apart, the knowledge base had grown, A3's database state had changed, the Codex CLI was
newer and the graders were different.


## Spend

Billed for the first run (2026-11-02), including the discarded pilot and setup probes:

| Model | Requests | Billed |
|---|---|---|
| Claude Opus 5.5 (Claude Code) | 1,004 | $46.02 (Claude Code reported $46.21) |
| gpt-6.1-sol (Codex) | 1,195 | $45.50 |
| Subagent models | – | $0.02 |
| **Total** | | **$91.54** |

Codex reports tokens but not cost. Estimated from list prices ($2 input, $0.10 cached input, $10 output per million
tokens), the Codex runs came to $19.40, 2.36× less than billed, and the budget guard based on that estimate didn't
hold its cap. Runs stopped there, which is why Codex has fewer repetitions. The Codex dollar figures above are the
estimates scaled by 2.36. Ratios don't depend on this if prices scale uniformly. If the whole gap sat in one price
component, the Codex `atlas` cost ratio would be 0.49×, 0.64× or 0.53×, and `dump` 3.19×, 2.21× or 1.85×; the
conclusions hold in every case. Lesson: cap budgets on billed spend, not on list-price estimates.

The smaller-model follow-up (2026-11-06), including three repeated runs:

| Model | Runs | Billed |
|---|---|---|
| Claude Haiku 5.5 (Claude Code) | 69 | $3.88 (Claude Code reported $0.90) |
| gpt-6-luna (Codex) | 66 | $1.78 (list-price estimate $0.90) |
| **Total** | | **$5.67** |

Neither CLI's figure was usable this time. Claude Code's reported cost was 4.3× below the bill: its Haiku 5.5 prices
appear to be out of date. The bill matches the recorded tokens exactly at $0.50 input, $0.05 cache read, $0.625
cache write and $2.50 output per million tokens, so the Claude Code costs in [Smaller models](#smaller-models) use
those prices. The Codex estimate was 1.98× below the bill, and the Codex costs are scaled by that factor. Grading
isn't included in either total.

## Limitations

- **One project, 9 questions.** Confidence intervals resample questions and are wide. In the first run the token
  result holds on every question for both agents; the quality result doesn't.
- **Possible rubric bias.** Rubric items were written from verified facts, but some phrasings match how the atlas
  words them. This may favour `atlas` and `dump` on quality; it doesn't affect tokens.
- **The atlas can be stale.** In the first run, the atlas still said the October nights weren't in the database;
  another pipeline had added rows three days earlier. Answers that relied on it repeated the claim, and no arm found
  the rows.
- **Imperfect blinding.** Answers that cite the atlas reveal their arm. Graders were told to ignore sources.
- **Ceiling effect.** In the first run, Codex without the atlas already passed 13/15, which leaves little room to
  show a quality gain. The smaller models had more room.
- **Derived costs** (see [Spend](#spend)). Codex costs are estimates scaled to the bill. Claude Code costs are as
  reported in the first run and recomputed from tokens in the follow-up.
- **Tool calls aren't comparable across agents.** Codex batches several commands into one call.
- **One contaminated run.** One Codex `none` run listed the hidden, empty atlas folder; nothing could leak from it.
- **Scoring takes the final message only.** One Claude Haiku `none` run gave its answer in an earlier message and
  ended with a short note, so it scored 0. The first run used the same rule.
- **Not reproducible as published.** The harness and questions refer to private research data, so they are not
  part of this repository.
