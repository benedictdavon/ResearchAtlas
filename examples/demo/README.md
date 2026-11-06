# Demo: a fictional bird-song project

`run_demo.py` builds a throwaway research project and four synthetic agent sessions about it (Codex, Claude Code,
Copilot), then runs the real `researchatlas` CLI through the whole workflow:

1. **extract + paths:** index the first three sessions and verify every path they mention. The deleted
   `labels/v1` comes back `missing`.
2. **knowledge + mark-reviewed:** install the cited knowledge base in [knowledge/](knowledge/) (in real use a
   coding agent writes it from the condensed sessions), then record those sessions as reviewed.
3. **find:** answer "where are the labels?" from the knowledge base first, then verified paths, then transcripts.
4. **refresh:** a week later the raw recordings move to an archive share and a new session records the move.
   `refresh` lists the unreviewed session, flags the cited path that no longer exists and surfaces the new one.

```bash
python examples/demo/run_demo.py                      # temporary folder, removed afterwards
python examples/demo/run_demo.py --dir /tmp/atlas-demo  # keep the world to inspect work/ and the knowledge files
```

Everything happens inside that folder; your real transcripts and config are not touched.
