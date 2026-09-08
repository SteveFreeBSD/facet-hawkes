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

### 1b. The pin is published (needs network)

CI checks the runtime out by object name, so the pin has to be reachable from
some pushed ref — not merely present in a local checkout.

```bash
cd /home/steve/apps/facet-runtime
PIN=$(grep -v '^#' ../facet-hawkes/deploy/facet-runtime.pin | tr -d '[:space:]')
git fetch -q origin
git branch -r --contains "$PIN"
```

**Expect:** at least one `origin/…` line. As of 2026-09-08 that is
`origin/feature/live-hawkes-next-slice`; `origin/main` is deliberately still
`f2e0907`, which predates `ANSWER_FORMS`. Nothing here should say `main`
until someone decides to advance it — in both repositories `main` is a frozen
release baseline and the current system is on the branch, so a default clone
lands on neither. See [Where the code is
published](CURRENT_STATE.md#where-the-code-is-published).

The strongest form of this check is the clone itself, which is what a new
machine actually does:

```bash
cd "$(mktemp -d)"
git clone -q https://github.com/SteveFreeBSD/facet-runtime.git
git -C facet-runtime checkout --detach "$PIN"
grep -c ANSWER_FORMS facet-runtime/src/facet_runtime/exact/__init__.py
```

**Expect:** the checkout succeeds and the grep reports at least 1. A failure
here means the published instructions cannot build a working system, which is
the exact defect the pin file exists to prevent.

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
uv run pytest -q tests/test_documentation.py tests/test_runtime_pin.py
cd /home/steve/apps/facet-runtime && uv run --frozen pytest -q tests/test_documentation.py
```

That covers, in both repositories: every local Markdown link and heading
anchor; one top-level heading per file; no active document asserting a
superseded topology or product name; no active document referencing a removed
legacy packet. The answer-capability authority and rendering have their own
executable check immediately below.

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

## 4b. The answer-capability gate

The executable boundary between what Facet emits and what this repository can
enter. It observes the exact answers built by the runtime's own test suite and
also keeps the 38-question live-course sweep. Offline, about five seconds.

```bash
cd /home/steve/apps/facet-hawkes
uv run pytest -q tests/test_answer_compatibility.py
python3 scripts/render_answer_capabilities.py
cd /home/steve/apps/facet-runtime && uv run --frozen pytest -q tests/test_answer_forms.py
```

**Expect:** 38 or more passing here, `ANSWER_CAPABILITIES.md is up to date`, and
the runtime's own form tests clean.

Two failures mean specific things. `undeclared compositions reached the
consumer` means a solver now emits an answer shape nothing has agreed to enter
— add an entry to `docs/answer-capabilities.json`, or declare it unsupported
with the code it is really refused by. `has drifted from
answer-capabilities.json` means the prose table was hand-edited; the JSON is
the authority, so re-render rather than reconciling by hand:

```bash
python3 scripts/render_answer_capabilities.py --write
```

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

**Expect:** `37/37 answered exactly, 1 correctly declined (0 wrong,
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

## 9. The fresh paired clone (needs network, takes a few minutes)

The strongest check there is, and the one the release audit calls for: build
the system from public URLs and nothing else.

```bash
cd "$(mktemp -d)"
git clone -q https://github.com/SteveFreeBSD/facet-hawkes.git
git clone -q https://github.com/SteveFreeBSD/facet-runtime.git
git -C facet-hawkes checkout -q feature/live-hawkes-next-slice
git -C facet-runtime checkout -q --detach \
  "$(grep -v '^#' facet-hawkes/deploy/facet-runtime.pin | tr -d '[:space:]')"
cd facet-hawkes
uv sync --frozen --extra dev
uv run ruff check . && uv run ruff format --check .
uv run python -m compileall -q src tests
uv run vulture src tests --min-confidence 80
uv run pytest -q
uv run python scripts/build_extension.py --check
uv run ethnos hawkes-coverage
```

**Expect** the same results as sections 2, 5 and 6 above: everything clean,
1720 or more tests passing, 37 validated packaged files, and 37/37 answered
exactly with 1 correctly declined. Passed on 2026-09-08.

Note the two checkout lines. Without them the clone lands on `main` in both
repositories, which is a frozen release baseline in one and a pre-`ANSWER_FORMS`
tree in the other — and the `uv sync` fails at import rather than at checkout,
which is a confusing place to learn it.

Delete the temporary directory afterwards; it holds a full second copy of both
repositories.

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
