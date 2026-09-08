# Verification checklist

Everything a verifier needs to confirm this repository and its sibling are
consistent, buildable and honest — with no live browser, no Hawkes session and
no model call. It is deliberately cheap: the whole list runs in about a minute.

Run it from a checkout with `../facet-runtime` beside it.

## 1. The two repositories agree

```bash
cd /home/steve/apps/facet-hawkes
grep -v '^#' deploy/facet-runtime.pin                 # the required runtime commit
git -C ../facet-runtime merge-base --is-ancestor "$(grep -v '^#' deploy/facet-runtime.pin)" HEAD \
  && echo "runtime is at or ahead of the pin"
```

**Expect:** one 40-character object name, then the confirmation line.
`tests/test_runtime_pin.py` asserts the same thing, plus that the README, the
migration checklist, the release runbook and the audit ledger all quote it and
that CI reads the file rather than restating a commit.

## 2. Facet-hawkes gates

These are exactly the CI steps, in CI's order.

```bash
cd /home/steve/apps/facet-hawkes
uv sync --frozen --extra dev
uv run ruff check .
uv run ruff format --check .
uv run python -m compileall -q src tests
uv run vulture src tests --min-confidence 80
uv run pytest -q
```

**Expect:** all clean; `pytest` at 1720 or more passing, 0 failing. Any failure
is a real failure — none of these is known-flaky and none needs a network.

## 3. Facet-runtime gates

`facet-runtime` has no CI workflow, so these are run by hand.

```bash
cd /home/steve/apps/facet-runtime
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen pytest -q
```

**Expect:** clean; 562 or more passing.

## 4. Documentation

```bash
cd /home/steve/apps/facet-hawkes
uv run pytest -q tests/test_documentation.py tests/test_runtime_pin.py tests/test_answer_capabilities.py
cd /home/steve/apps/facet-runtime && uv run --frozen pytest -q tests/test_documentation.py
```

That covers, in both repositories: every local Markdown link and heading
anchor; one top-level heading per file; no active document asserting a
superseded topology or product name; no active document referencing a removed
legacy packet; every `answer.form` having a row in `ANSWER_CAPABILITIES.md`.

The tests judge topology and product wording. They do not judge **model
aliases**, because whether a name exists is a fact about a machine rather than
about the text. Sweep for the ones that do not exist on this host:

```bash
cd /home/steve/apps/facet-hawkes
git grep -n -i -E 'gemma-python|precalc-local|qwen3-coder|gemma4:' -- '*.md' \
  | grep -v '^docs/history/' | grep -v '^extension/CHANGELOG.md'
ollama list
```

**Expect** every remaining hit to be in a file that already declares itself
historical, and nowhere else:

| File | Why a hit is expected there |
|---|---|
| `docs/PRECALCULUS.md` | historical procedure, bannered at the top |
| `docs/VISION_MATH_ARCHITECTURE.md` | historical staging record, bannered at the top |
| `docs/MIGRATION.md` | one line, inside a warning about the alias recipe that used to be here |
| `docs/CURRENT_STATE.md`, `README.md` | one line each, naming `precalc-local` as the stale `precalc-bench` default |
| `examples/*.md` | provenance of artifacts produced on `caspian`, bannered |

A hit anywhere else — especially in an install or migration step a reader will
paste — is a regression. `ollama list` on this host shows `qwen3.5:2b`,
`qwen3.5:4b`, `qwen3.5:9b` and `gpt-oss:20b`; anything else a document tells
you to run is a name this machine does not have.

## 5. The package

```bash
cd /home/steve/apps/facet-hawkes
uv run python scripts/build_extension.py --check      # validates without writing
uv run python scripts/build_extension.py              # writes, and prints its digest
sha256sum dist/facet-hawkes-0.46.0-unsigned.xpi
```

**Expect:** 37 packaged files, and the same digest on two consecutive builds
from unchanged sources. The digest recorded in `extension/RELEASE.md` and the
audit ledger belongs to the **6 September audit** and will not match a current
build — that is stated in both places and is not a defect. Re-record it only
when the gates are re-run for a signing.

## 6. Offline solver coverage

```bash
cd /home/steve/apps/facet-hawkes
uv run ethnos hawkes-coverage
```

**Expect:** `36/36 answered exactly, 1 correctly declined (0 wrong,
0 unrecognized, 0 declined by the solver)`. No model runs; it takes about a
second.

## 7. The installed helper and registration

Local state rather than the checkout, so this is the one section that can pass
in a repository and fail on a machine.

```bash
python3 deploy/firefox/install_native_host.py --check
echo '{"facet_protocol_version": 2, "operation": "solve_math",
       "request_id": "verify-1",
       "problem": {"instruction": "Simplify.", "expressions": ["(x+1)*(x-1)"],
                   "answer_parts": 1}}' | /home/steve/.local/bin/facet-remote
```

**Expect:** three `ok:` lines from the first, and from the second a `status:
"ok"` result whose answer carries a `form` field, `route: "exact"` and
`model_calls: 0`. A missing `form` means the installed helper predates the pin
— reinstall with `uv tool install --force --reinstall .` in `../facet-runtime`.

## 8. Transport

```bash
python3 scripts/observe_live_hawkes.py | sed -n '/^FACET/,/^$/p'
```

**Expect:** `transport local  -> this machine
/home/steve/.local/bin/facet-remote`. Anything naming `ssh` or an address means
`FACET_TRANSPORT` is set in that environment; the local subprocess is the
default and every live solve should use it.

This command reads only. It never drives the browser and cannot wake a
suspended event page.

## What this checklist does not cover

- **Signed-artifact acceptance.** The unsigned XPI installing in a throwaway
  profile is not evidence about a Mozilla-signed build in the owner's normal
  profile. That is mode A in [Hawkes development
  flow](HAWKES_DEVELOPMENT_FLOW.md) and needs a person.
- **Anything requiring Hawkes.** No step here opens a lesson, and none should.
- **Model behaviour.** `facet prompts --live` in `../facet-runtime` exercises
  the real prompts against a real model; it is slow, needs Ollama, and is not
  part of this list.
- **A current acceptance figure.** There is not one, deliberately — see
  [Runtime, models and deployment](RUNTIME_AND_DEPLOYMENT.md#which-model-answers-what).
