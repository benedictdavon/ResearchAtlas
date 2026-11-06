"""Transcript sources. SOURCES maps each source name to its module, in candidate order (codex, claude, copilot).

A source is one module here that provides this interface (a new source adds a module and one SOURCES entry):
  NAME                        str, e.g. "codex": the "source" of its candidates and of its output files.
  discover(cfg, paths=None)   -> (cands, skipped). cands: dicts with source, kind, id, short, path (Path),
                              parent_id, cwd, meta (dict). skipped: int, sessions deliberately skipped
                              (codex: guardians). paths: pre-listed files (codex uses it; others ignore it).
                              Return ([], 0) if the module's keys are missing from cfg["sources"].
  prepare(cfg, ctx)           Called once per extract, before parsing. May add keys to ctx.
  condense(c, ctx, body_path) -> st. Parse one candidate into body_path; return the parse state.
  title(c, st, ctx)           -> str or None. Source title, tried before the first-user-text fallback.
"""
from . import claude, codex, copilot

SOURCES = {"codex": codex, "claude": claude, "copilot": copilot}
