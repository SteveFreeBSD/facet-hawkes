"""Public SQLite storage API facade.

Implementation lives in focused modules:

- ``db_core``: connection, schema, documents, pages, and chunks
- ``db_sections``: section labels and section status
- ``db_outputs``: extraction runs, model outputs, and normalized records
- ``db_query``: inspection, FTS search, and retrieval context
- ``db_structure``: structured-output status
- ``db_reports``: quality, export, and database inventory reports
- ``db_agent``: agent review run and finding persistence
"""

from __future__ import annotations

from .db_core import (
    clear_document_outputs,
    connect,
    get_document,
    init_db,
    list_chunks,
    list_documents,
    list_pages,
    rebuild_fts_index,
    save_chunks,
    save_document_pages,
)
from .db_outputs import (
    backfill_chunk_summaries,
    create_extraction_run,
    finish_extraction_run,
    refresh_normalized_records,
    save_extraction_result,
    save_model_output,
)
from .db_query import (
    add_continuation_context_chunks,
    chunk_records,
    context_chunks,
    inspect_chunk,
    inspect_page,
    list_structured_records,
    search_chunks,
)
from .db_reports import db_info, export_document, quality_report
from .db_sections import apply_section_preset, section_label_status
from .db_structure import (
    list_structure_chunk_status,
    select_chunks_for_structure,
    structure_status,
)
from .db_agent import (
    agent_report_summary,
    create_agent_run,
    finish_agent_run,
    save_agent_findings,
)

__all__ = [
    "add_continuation_context_chunks",
    "agent_report_summary",
    "apply_section_preset",
    "backfill_chunk_summaries",
    "chunk_records",
    "clear_document_outputs",
    "connect",
    "context_chunks",
    "create_agent_run",
    "create_extraction_run",
    "db_info",
    "export_document",
    "finish_extraction_run",
    "finish_agent_run",
    "get_document",
    "init_db",
    "inspect_chunk",
    "inspect_page",
    "list_chunks",
    "list_documents",
    "list_pages",
    "list_structure_chunk_status",
    "list_structured_records",
    "quality_report",
    "rebuild_fts_index",
    "refresh_normalized_records",
    "save_chunks",
    "save_document_pages",
    "save_extraction_result",
    "save_agent_findings",
    "save_model_output",
    "search_chunks",
    "section_label_status",
    "select_chunks_for_structure",
    "structure_status",
]
