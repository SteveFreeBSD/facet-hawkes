"""The exact polynomial expansion, which now lives on the Facet side.

Re-exported from `facet_runtime.exact.polynomial` for the same reason as
`symbolic_solver`: Facet routes between exact mathematics and reasoning, so the
exact implementation lives where that routing happens, and Ethnos's local paths
call the same one rather than a copy of it.
"""

from __future__ import annotations

from facet_runtime.exact.polynomial import (
    PolynomialExpansion,
    answer_polynomial_product,
    expand_first_polynomial_expression,
)

__all__ = [
    "PolynomialExpansion",
    "answer_polynomial_product",
    "expand_first_polynomial_expression",
]
