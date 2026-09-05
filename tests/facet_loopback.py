"""Run the real Facet remote helper in-process, over the real protocol.

The point of the Facet boundary is that Ethnos hands over a question and Facet
decides how it gets answered. A test that stubs out the whole of Facet proves
only that Ethnos can read a reply it wrote itself; it cannot prove that the
routing decision is made on the far side, because in such a test there is no
far side.

So this substitutes the *transport* and nothing else. Ethnos builds its real
request, `facet_runtime.remote.handle` parses it, Facet's real router runs the
real deterministic solvers, and the real envelope comes back through Ethnos's
real validation. Only the model is fake, because a model is the one thing that
cannot be run in a unit test -- and faking it is also what makes the two routes
distinguishable: if the fake ever speaks, reasoning ran.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field

from facet_runtime.adapters.base import AdapterOutput, ExecutionMetrics

GPU_DEVICE = "AMD Radeon 890M Graphics (RADV STRIX1)"


@dataclass
class FakeAdapter:
    """One compute path. It records every prompt the reasoning route sent it."""

    backend: str
    available: bool = True
    text: str = "FINAL ANSWER: 42"
    model: str = "gpt-oss:20b"
    runtime: str = "Ollama 0.33.2"
    device: str = GPU_DEVICE
    prompts: list[str] = field(default_factory=list)

    def is_available(self) -> bool:
        return self.available

    def run(self, prompt: str) -> AdapterOutput:
        self.prompts.append(prompt)
        return AdapterOutput(
            text=self.text,
            runtime=self.runtime,
            model=self.model,
            device=self.device,
            metrics=ExecutionMetrics(
                prompt_tokens=11, generated_tokens=9, prefill_tps=504.0, decode_tps=21.2
            ),
            evidence={"source": "ollama /api/ps", "device_resident_fraction": 1.0},
        )


@dataclass
class Loopback:
    """What crossed to Facet, and what Facet's reasoning route was asked."""

    requests: list[dict] = field(default_factory=list)
    adapters: dict[str, FakeAdapter] = field(default_factory=dict)

    @property
    def prompts(self) -> list[str]:
        """Every prompt a model actually saw. Empty means nothing reasoned."""
        return [
            prompt for adapter in self.adapters.values() for prompt in adapter.prompts
        ]

    @property
    def problems(self) -> list[dict]:
        """The `problem` object of every solve request that crossed."""
        return [request["problem"] for request in self.requests if "problem" in request]


def facet(monkeypatch, **overrides) -> Loopback:
    """Point Ethnos's Facet transport at a real in-process Facet.

    `overrides` replace named backends, so a test can make an accelerator
    unavailable or give the reasoning route a particular reply.
    """
    from facet_runtime.remote import handle

    adapters: dict[str, FakeAdapter] = {
        name: FakeAdapter(name, device=f"fake {name} device")
        for name in ("cpu", "gpu", "npu")
    }
    adapters["gpu"].device = GPU_DEVICE
    for name, adapter in overrides.items():
        adapters[name] = adapter
    loopback = Loopback(adapters=adapters)

    def fake_run(argv, *, input, **kwargs):  # noqa: A002 - subprocess's own name
        loopback.requests.append(json.loads(input))
        envelope, code = handle(input.encode("utf-8"), adapters=adapters)
        return subprocess.CompletedProcess(
            argv, code, stdout=json.dumps(envelope) + "\n", stderr=""
        )

    monkeypatch.setattr("ethnos.facet_client.subprocess.run", fake_run)
    return loopback


def reasoning(text: str, **changes) -> dict[str, FakeAdapter]:
    """Adapters whose reasoning route answers with `text`."""
    made = {}
    for name in ("cpu", "gpu", "npu"):
        fields = dict(changes)
        fields.setdefault(
            "device", GPU_DEVICE if name == "gpu" else f"fake {name} device"
        )
        made[name] = FakeAdapter(name, text=text, **fields)
    return made
