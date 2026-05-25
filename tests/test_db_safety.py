import pytest

from ethnos.db_core import quote_identifier


def test_quote_identifier_rejects_unknown_sql_identifiers():
    assert quote_identifier("chunks") == '"chunks"'
    with pytest.raises(ValueError, match="Unsafe SQL identifier"):
        quote_identifier("chunks; DROP TABLE chunks; --")
