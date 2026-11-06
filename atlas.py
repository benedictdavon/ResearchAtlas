#!/opt/conda/bin/python
"""ResearchAtlas CLI: mine agent transcripts into a verified research knowledge base.

Subcommands (see docs/04_mvp_spec.md):
  extract   condensed per-session markdown + sessions.jsonl + per-session path hits
  paths     aggregate path hits into paths.jsonl and verify each path (timeout-guarded)
  refresh   run extract + paths, then report sessions to review, atlas feedback, broken cited paths
            and new uncited paths (writes no review state)
  mark-reviewed  record sessions as covered by knowledge/ in the review ledger (D25)
  find      search knowledge/ (by section), paths.jsonl and condensed sessions

Stdlib only. Run with /opt/conda/bin/python (3.11).
"""
import sys

from atlaslib.cli import main
from atlaslib.core import (ATLAS_DIR, BLANK_RUN_RE, GREP_CONTEXT_RE, MD_HEADING_RE, PATH_GROUP, PATH_KINDS,
                           PATH_RE_TMPL, PATH_STOP, _KIND_BY_EXT, _iso, bullet, clean_path, cmd_line,
                           collapse_ws, heading, load_config, new_state, note_ts, parse_ts, path_regex,
                           read_json, read_jsonl, scan_obj, scan_paths, tidy_body, truncate, under,
                           walk_jsonl, work_paths, write_jsonl)
from atlaslib.extract import (cmd_extract, discover_candidates, fresh, finalize, mention_needles, outputs_exist,
                              parse_candidate, raw_mentions, remove_stale, select_candidates, session_title,
                              write_condensed, write_pathhits)
from atlaslib.find import FIND_WIDTH, cmd_find, find_knowledge, find_paths, find_sessions, snippet
from atlaslib.paths import (PATH_MOUNT_TIMEOUT_LIMIT, VERIFY_FIELDS, _PROBE_SRC, _PathProbe, _load_pathhits,
                            _path_kind, _path_mount, _path_result, _path_root, _paths_aggregate, _paths_now_iso,
                            _paths_ts_iso, _print_counts, _print_paths_summary, cmd_paths, verify_paths)
from atlaslib.refresh import (CITE_PATH_END_RE, CITE_SPAN_RE, CITE_TEMPLATE_CHARS, CITE_TEMPLATE_TOKENS,
                              FREQ_CAP, FREQ_SKIP_NAMES, FREQ_SKIP_PARTS, atlas_feedback, check_cited, cited_paths,
                              cmd_refresh, expand_cited, new_frequent_paths, print_sessions, run_quiet)
from atlaslib.review import (cmd_mark_reviewed, condensed_digest, load_ledger, parse_report, pending_sessions,
                             save_ledger, session_key)
from atlaslib.sources.claude import (CLAUDE_DROP_PREFIXES, claude_condense, claude_first_cwd, claude_flush,
                                     claude_tool_bullets, claude_user_record)
from atlaslib.sources.codex import (CODEX_DROP_CALLS, CODEX_MESSAGE_CALLS, INJECTED_CODEX, JS_STR, codex_class,
                                    codex_call_bullets, codex_condense, codex_custom_bullets, codex_interagent,
                                    codex_message, codex_meta, codex_record, codex_session_index, codex_user_part,
                                    discover_codex, exec_commands, js_literal, patch_targets, payload_hashes,
                                    text_of)

if __name__ == "__main__":
    sys.exit(main())
