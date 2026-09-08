# Historical record

Nothing in this directory describes the system as it is now. It is kept because
a measurement belongs to the thing that produced it, and deleting evidence
because it is old leaves a later reader with no way to check a claim.

**Read [Current state](../CURRENT_STATE.md) first.** Then use this page to find
out what a number here was measured on, and why it is not restated.

## What is here, and what replaced it

| Document | What it records | Read instead |
|---|---|---|
| [Current baseline](CURRENT_BASELINE.md) | The accepted app/data/model baseline on `caspian`, last verified 2026-07-19, against a model alias that exists only on that machine | [Runtime, models and deployment](../RUNTIME_AND_DEPLOYMENT.md) |
| [Performance tuning](PERFORMANCE_TUNING.md) | The benchmark protocol, the measured 4K/8K and batching decisions, and the rejected candidates — all on `caspian` | [Runtime, models and deployment](../RUNTIME_AND_DEPLOYMENT.md) |
| [Caspian host profile](CASPIAN_HOST.md) | `caspian`'s hardware, Vulkan/Ollama service block, kernel and VM settings. Still the reference for reproducing the numbers above *on that host* | [Runtime, models and deployment](../RUNTIME_AND_DEPLOYMENT.md) |
| [Hawkes Firefox extension plan](HAWKES_FIREFOX_EXTENSION.md) | The pre-implementation design plan. Its native-messaging protocol, permission set and insertion strategy are not what was built | [`extension/README.md`](../../extension/README.md) |
| [Hawkes end-to-end proof](HAWKES_E2E_PROOF.md) | The first complete safe path, 2026-09-02, in a throwaway Marionette profile on lesson 1.3 | [Answer capabilities](../ANSWER_CAPABILITIES.md) for what is proven now |
| [Hawkes live findings](HAWKES_LIVE_FINDINGS.md) | The 2026-09-03 live session on add-on `0.39.0-unsigned`. Every defect it names was fixed across 0.39.0–0.41.3 and the fixes are in the changelog | [Retained failure ledger](../FAILURE_LEDGER.md) for failures now |
| [Live Hawkes coverage sweep](LIVE_HAWKES_COVERAGE_2026-09-05.md) | An observation-only sweep of lesson 3.3 on add-on 0.45.0, before the table, pair, fraction and graph routes landed | [Answer capabilities](../ANSWER_CAPABILITIES.md) |

## The two names

The Python package `ethnos`, the add-on ID `ethnos-hawkes@local`, the
native-messaging host `ethnos_hawkes` and the `ethnos:*` internal messages are
**current** identifiers, not historical ones. They are deliberately unchanged
because renaming them orphans an installed profile and buys nothing a user can
see. The product is Facet Hawkes Assistant, and nothing a user reads says
Ethnos. [The Ethnos-Facet boundary](../FACET_BRIDGE.md#a-note-on-the-two-names)
is the reference, and the full retained list with reasons is in
[`extension/RELEASE.md`](../../extension/RELEASE.md).

`caspian` is genuinely historical: an earlier host that is not in the live path.
So is the `ethnos-caspian` git remote, kept as legacy history.

## Adding to this directory

Move a document here when it is still evidence but no longer instruction, and
give it a header saying so in its own first lines. Add a row above naming what
it recorded and what to read instead. Do not delete it merely because it is
old, and do not leave it in `docs/` where a reader will follow it as current.
