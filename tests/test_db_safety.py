import pytest

from ethnos.db_core import quote_identifier
from ethnos.db_query import _is_fts_query_syntax_error


def test_quote_identifier_rejects_unknown_sql_identifiers():
    assert quote_identifier("chunks") == '"chunks"'
    with pytest.raises(ValueError, match="Unsafe SQL identifier"):
        quote_identifier("chunks; DROP TABLE chunks; --")


def test_fts_fallback_only_handles_match_syntax_errors():
    assert _is_fts_query_syntax_error(Exception("fts5: syntax error near /")) is True
    assert (
        _is_fts_query_syntax_error(Exception("database disk image is malformed"))
        is False
    )
