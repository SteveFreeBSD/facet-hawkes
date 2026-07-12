# Code Review

Findings from code reviews through 2026-06-27. The full test suite passes,
Ruff/Vulture are clean, and `gemma-python` remains the `caspian` baseline. The
findings below are source-verified against the current tree.

For model-level optimization recommendations that stay on `gemma-python`, see
the "Getting More From gemma-python" section in
[`PERFORMANCE_TUNING.md`](PERFORMANCE_TUNING.md).

## Bugs

### MC/Choice/Essay answers bypass think configuration

Status: fixed.

`_mc_chat_request_kwargs` in
[`ollama_client.py`](../src/ethnos/ollama_client.py) previously hardcoded
`"think": False` instead of accepting a `think` parameter and calling
`_add_think_option`. Because `_chat_mc` is used by `answer_mc_question`,
`answer_choice_question`, and `answer_essay_question`, all three answer paths
silently ignored the user's think setting (`ETHNOS_OLLAMA_THINK`, profile
`think` field).

**Fix applied**: `_mc_chat_request_kwargs` and `_chat_mc` now accept and forward
`think`; all three public answer functions accept `think`; quiz benchmark
commands pass `settings.ollama_think`.

**Former impact**: Blocked future think experimentation on quiz answer paths and
made profile behavior less transparent during hybrid/new-model evaluation.

### Assert in production code

Status: fixed.

`agent_loop.py` previously used `assert final is not None` after extracting
`action.final_review`. Python's `-O` flag strips asserts. The Pydantic
validator `require_final_for_finalize` should prevent this, but a dict bypass
or future refactor could reach this path.

**Fix applied**: Replaced with `if final is None: break` to fall through to the
deterministic fallback path.

### Dead MCSelection class

Status: fixed.

[`ollama_client.py`](../src/ethnos/ollama_client.py) previously defined an
unused `MCSelection` Pydantic model. The schema is built manually by
`_mc_selection_schema()`, and the class hardcoded `Literal["A", "B", "C", "D"]`
which would have been wrong for quizzes with 2, 5, or 6 options.

**Fix applied**: Removed the class and its unused `BaseModel`, `ConfigDict`, and
`Literal` imports.

## Cleanup

### Private symbols in db.py facade

Status: fixed.

[`db.py`](../src/ethnos/db.py) imports and re-exports 8 underscore-prefixed
internal helpers (`_chunk_from_row`, `_chunk_from_status_row`, `_ensure_column`,
`_is_study_content_role`, `_chunk_source_pages`,
`_delete_normalized_chunk_records`, `_record_source_pages`,
`_should_persist_study_records`) in `__all__`. No test or source file imports
them through the facade.

**Fix applied**: Removed private names from the import block and `__all__`.
Tests and internal code that need them should import from the specific submodule
(`db_core`, `db_outputs`) directly.

### Duplicated text-clipping logic

Status: fixed.

The pattern `compact[:max_chars - 3].rstrip() + "..."` appeared in several
places, including:

- `agent_tools.py` `_clip` (~line 680)
- `qa.py` `_preview_text` (~line 732)
- `quiz_core.py` `limit_option_text` (~line 262)

**Fix applied**: Consolidated whitespace compaction and ellipsis truncation into
[`text_utils.py`](../src/ethnos/text_utils.py) and routed CLI formatting,
quiz-core option truncation, QA previews, and agent snippets through it.

### Duplicated stopword sets

Status: fixed.

`agent_tools.py` `_significant_terms` (~line 688) defines its own stopword set.
`qa.py` `QUESTION_STOPWORDS` (~line 14) defines another. They overlap but
differ. Adding a word to one may miss the other.

**Fix applied**: Centralized stopword constants in
[`text_utils.py`](../src/ethnos/text_utils.py) while preserving the distinct
term-selection behavior for QA, agent review, quiz generation, and prompt
guidance.

### client: object type annotations

Status: fixed.

The Ollama client was typed as `object`, limiting type-checker coverage around
chat call shape, fake clients, and lifecycle methods.

**Fix applied**: Added `OllamaClientProtocol` in
[`ollama_client.py`](../src/ethnos/ollama_client.py) and used it across the
Ollama wrapper, ask command helper, and agent loop.

## Architecture Observations

### Prompt template caching does not invalidate on file change

Status: fixed.

`ollama_client.py`, `qa.py`, and `quiz_prompts.py` previously cached prompt
templates with `lru_cache` keyed by `Path`. Editing a prompt file during a
long-running Python session used the stale cached version until the process
restarted.

**Fix applied**: Added [`prompt_cache.py`](../src/ethnos/prompt_cache.py), which
keys cached prompt reads by resolved path, file mtime, and file size.

### No FTS5 rebuild command

Status: fixed.

The FTS5 triggers in `db_core.py` keep the index in sync during normal
operation. If the index corrupts (crash during write), there is no CLI command
to rebuild it. SQLite supports
`INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')`.

**Fix applied**: Added `rebuild_fts_index()` and the `uv run ethnos
rebuild-fts` CLI command for recovery.

### No graceful shutdown for the chat loop

Status: covered.

The `chat` command runs an input loop. A keyboard interrupt during an Ollama
call must exit cleanly instead of surfacing a raw traceback.

**Verification added**: The chat loop's existing `KeyboardInterrupt` handler now
has regression coverage for interrupts during answer generation.

### No progress indication for long runs

Status: fixed for Agent Review; structure already emits chunk-level progress.

Full-quiz `agent-review` runs can take many minutes on CPU with limited
progress feedback. Even a simple `item N/M` counter on stderr would help.

**Fix applied**: `agent-review` now emits `item N/M` progress to stderr before
each item.

### No per-item timeout in agent review

Status: fixed.

If one quiz item causes a slow tool loop, the entire review blocks. The global
Ollama HTTP timeout protects individual requests, but a per-item timeout would
cover the full model/tool loop and allow deterministic fallback for that item.

**Fix applied**: Added `--item-timeout` to `agent-review`. Timed-out items
receive an `agent_item_timeout` quality finding and continue through
deterministic fallback.

### Quiz benchmark interruption lost completed work

Status: fixed.

`quiz-bench` previously wrote its report only after the final item. An interrupt
during a CPU-heavy run discarded every completed answer and surfaced a raw
traceback.

**Fix applied**: Reports now use atomic per-item checkpoints. `--resume`
continues only when the document, quiz, model, item prefix, and run configuration
match. `verify-answer-key` rejects incomplete checkpoints.

### Quiz follow-up required full reruns and accepted inconsistent evidence

Status: fixed.

`quiz-bench` previously required rerunning the full quiz after a small number of
model misses. It also accepted schema-valid answers whose evidence was truncated
or described a different option than the emitted label, and compound guidance
recognized “All of the above” but not Canvas variants such as “All possible
answers.”

**Fix applied**: Repeatable `--item-id` filtering creates complete targeted
reports, while one bounded consistency retry checks validation, citations,
source-derived recommendations, and evidence/label agreement. Reports retain all
attempts and retry reasons. Compound guidance now covers the supported “All”
wording variants without consulting the instructor key.

### Anchored quiz prompts included unrelated retrieval candidates

Status: fixed.

Explicit source chunks were prioritized but unrelated FTS candidates were still
appended to the model context. Sparse questions could therefore receive correct
anchored evidence alongside distracting text from another chapter.

**Fix applied**: Validated source chunks are now the complete model context for
anchored items. Retrieval candidates remain available in diagnostics.

### Multiple-response output lacked key and scoring support

Status: hardened.

An experimental response shape accepted several selected labels while the quiz
schema and scoring path still represented one correct label. This could score a
partial match as correct.

**Fix applied**: The incomplete response shape was removed. Validation now
rejects explicit “select/choose/pick two/all” prompts until a first-class
multiple-response item type, list-valued keys, and set-based scoring are added.

## Review Checklist

Use this list when addressing findings:

- [x] Fix `_mc_chat_request_kwargs` think bypass.
- [x] Fix `_chat_mc` to accept and forward `think` parameter.
- [x] Thread `think` through `answer_mc_question`, `answer_choice_question`,
      `answer_essay_question`.
- [x] Replace `assert final is not None` with `if final is None: break`.
- [x] Remove dead `MCSelection` class and unused imports.
- [x] Remove private symbols from `db.py` `__all__` and imports.
- [x] Consolidate text-clipping utility.
- [x] Consolidate stopword sets.
- [x] Add `Protocol` typing for Ollama client.
- [x] Add `rebuild-fts` CLI command.
- [x] Add progress indication for `agent-review`.
- [x] Add prompt-template cache invalidation for long-running tuning sessions.
- [x] Add graceful shutdown regression coverage for the interactive `chat` loop.
- [x] Add per-item timeout for the full Agent Review model/tool loop.
- [x] Add atomic `quiz-bench` checkpoints and compatible resume validation.
- [x] Add targeted quiz reruns and bounded evidence/selection retries with
      attempt diagnostics.
- [x] Recognize supported Canvas “All possible answers” compound variants.
- [x] Keep anchored quiz prompts free of unrelated retrieval candidates.
- [x] Reject unsupported multiple-response quiz items instead of mis-scoring
      them.
