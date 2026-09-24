"""Pytest plugin that records every exact answer built by facet-runtime.

The compatibility gate loads this plugin into facet-runtime's own test suite.
It deliberately observes the runtime at its answer boundary instead of
repeating the solver cases or their mathematics in this repository.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_CURRENT_TEST = ""
_EMISSIONS: list[dict[str, object]] = []


def pytest_configure() -> None:
    from facet_runtime.exact import ExactSolution

    original = ExactSolution.__init__

    def recording_init(self, *args, **kwargs) -> None:
        original(self, *args, **kwargs)
        _EMISSIONS.append(
            {
                "test": _CURRENT_TEST,
                "display": self.display,
                "entry": self.entry,
                "parts": list(self.parts),
                "entry_mode": self.entry_mode,
                "form": self.form,
                # Both sides of an equation answer, when it is one. The gate
                # classifies what the host would type, and for this family that
                # is two different strings depending on the page.
                "relation": (
                    None
                    if self.relation is None
                    else {
                        "subject": self.relation.subject,
                        "value": self.relation.value,
                    }
                ),
                "intercepts": (
                    None
                    if self.intercepts is None
                    else {
                        axis: (
                            None
                            if getattr(self.intercepts, axis) is None
                            else {
                                "x": getattr(self.intercepts, axis).x,
                                "y": getattr(self.intercepts, axis).y,
                            }
                        )
                        for axis in ("x", "y")
                    }
                ),
                "inequality_pair": (
                    None
                    if self.inequality_pair is None
                    else {
                        "left": {
                            "left": self.inequality_pair.left.left,
                            "relation": self.inequality_pair.left.relation,
                            "right": self.inequality_pair.left.right,
                        },
                        "connector": self.inequality_pair.connector,
                        "right": {
                            "left": self.inequality_pair.right.left,
                            "relation": self.inequality_pair.right.relation,
                            "right": self.inequality_pair.right.right,
                        },
                    }
                ),
                "method": self.method,
            }
        )

    ExactSolution.__init__ = recording_init


def pytest_runtest_setup(item) -> None:
    global _CURRENT_TEST
    _CURRENT_TEST = item.nodeid


def pytest_sessionfinish() -> None:
    destination = os.environ.get("FACET_EXACT_EMISSION_RECORD")
    if destination:
        Path(destination).write_text(json.dumps(_EMISSIONS), encoding="utf-8")
