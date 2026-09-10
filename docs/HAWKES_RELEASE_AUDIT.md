# Facet Hawkes Assistant release audit ledger

This ledger runs newest first. The current candidate is the first section; the
sections after it are the record of superseded and historical ones, kept for
audit and rollback context. A hash or a gate count anywhere below the current
section belongs to the version its heading names and must not be quoted as
though it described today's build.

## Current: 0.46.0 — prepared for publication approval

**Audited:** 6 September 2026

**Status:** **unsigned candidate complete; approved repository strategy staged
locally, external publication actions not yet authorized.**

| Record | Value |
|---|---|
| Product name | Facet Hawkes Assistant |
| Packaged-source baseline | recorded as `fc3f5e4a…`, which resolves to no object in this repository. Treat the audit as anchored to its date, not to that name |
| Required Facet runtime | `887da0e3c2482b6683650cf0437b31eba69e364c` |
| Candidate artifact | `dist/facet-hawkes-0.46.0-unsigned.xpi` |
| Candidate SHA-256 | `6bf24fb9744da4b375171530cee9d0c2069a0e7c4be3536161ad6bd983215d64`, as audited on 6 September. The source line has advanced since; rebuild to get today's |
| Packaged members | 33, as audited. A current build packages more |
| Add-on ID | `ethnos-hawkes@local`, deliberately unchanged |
| Native host | `ethnos_hawkes`, deliberately unchanged |
| Reproducibility | two unchanged builds produced the same SHA-256 |
| Hawkes repository suite | 1203 passed, as audited on 6 September |
| Facet runtime suite | 291 passed, as audited on 6 September |
| Static gates | Ruff check and format, compileall, Vulture, and 3 documentation checks passed |
| Mozilla validator | `web-ext` 10.6.0 under Node 22.23.2: 0 errors, 0 warnings, 0 notices |
| Archive | integrity passed; exact packaged archive linted |
| Browser gate | unsigned XPI installed active in a clean throwaway Firefox 155.0.1 profile; Settings and popup loaded without fatal error |
| Canonical public repository | `https://github.com/SteveFreeBSD/facet-hawkes` — to be created after explicit approval |
| Companion topology | sibling `facet-hawkes` + `facet-runtime`; CI pins runtime `887da0e` |
| Remaining prerequisites | all three publication prerequisites were first met on 2026-09-08 and have held since: the pinned runtime is published on its branch, the canonical Hawkes repository is populated, and a fresh public sibling clone passed. What remains is external and is not a repository state: Mozilla signing, then signed-artifact physical acceptance |

> **Read this section as a dated audit, not as today's build.** Every number in
> it belongs to 6 September 2026. Work has landed since — drawn-box fractions,
> radio groups, point plotting, and the move from an SSH loopback to a local
> `facet-remote` subprocess — so the digest, the file count and the suite
> totals above are all lower than a rebuild produces. Signing requires a fresh
> run of the gates with its own recorded evidence; see
> [Current state](CURRENT_STATE.md) for where the system actually is.

0.46.0 makes the answer a deterministic score shared by insertion timing,
visuals, panel narration, and local music. The established Hawkes solve,
ownership, editor, and never-submit boundaries are unchanged. Cadence adds no
permission, sample, model, runtime, or network dependency, and its full live
evidence was completed before this release audit; it was not redesigned or
re-soaked here.

The candidate itself is reproducible. A fresh sibling checkout using the local
runtime checkpoint imports `facet_runtime.solve` and passes extension
validation. Paired with the runtime's *default* branch it does not: that branch
was `b6ffa6b0acbb036cacbdcc8ceed879f7de1c6e78` when this was audited and is
`f2e09071415907cbbe1b4b905af9af6473098e8b` now, and both predate the symbols
this checkout imports. Publication therefore had to push the runtime first.

**All three steps are done, as of 2026-09-08.** Both repositories published
their `feature/live-hawkes-next-slice` branch, which is where the current
system lives; both `main` branches were deliberately left frozen at their
release baselines, so a default clone still lands on neither. The install and
migration instructions name the branch for that reason.

The fresh-clone proof was then run as specified — both repositories cloned from
their public URLs and nothing else, `facet-hawkes` on the branch,
`facet-runtime` detached at the pin, `uv sync --frozen --extra dev`, and the
whole CI sequence: ruff check, ruff format, compileall, vulture, 1720 tests,
the package build at 37 validated files, and the offline solver sweep at 36/36
answered with 1 correctly declined. All passing.

What remains is external and is not a repository state: Mozilla signing, and
then signed-artifact physical acceptance in the owner's normal profile, which
only mode A can support.

The selected strategy retains the existing sibling path dependency. The public
README, migration checklist, manifest homepage, CI badge, and CI checkout now
consistently name `SteveFreeBSD/facet-hawkes`; CI fixes the sibling runtime at
`887da0e3c2482b6683650cf0437b31eba69e364c`. The old Ethnos repository is not a
Facet Hawkes publication target. The private `ethnos-caspian` remote remains
useful as legacy history and need not be removed.

There is no permission, host, native-protocol, data-collection, or compatibility
identifier change. Mozilla signing and signed-artifact physical acceptance
remain later external gates and were not attempted.

## Superseded: 0.43.0 candidate

**Prepared:** 4 September 2026

**Status:** **release candidate complete; pending Mozilla signing and signed-XPI
physical acceptance.**

| Record | Value |
|---|---|
| Product baseline | `bb1e66aa66de0506be1558ad26841b82b9273091` |
| Candidate artifact | `dist/ethnos-hawkes-0.43.0-unsigned.xpi` |
| Candidate SHA-256 | `3c19a69b41af3a82ab4ef1f2723da9b6b637ac37bb1419d8bf2eb966ef597001` |
| Packaged members | 30 |
| Reproducibility | two unchanged builds produced the same SHA-256 |
| Focused cadence/extension tests | 168 passed |
| Hawkes-focused tests | 349 passed |
| Full repository suite | 825 passed |
| Static/documentation gates | Ruff check and format passed; 3 link checks passed |
| Browser gates | isolated extension harness 17/17; Settings smoke 17/17 |
| Mozilla validator | `web-ext lint --warnings-as-errors`: 0 errors, 0 warnings, 0 notices |
| Remaining external gates | Mozilla unlisted signing, then normal-Firefox physical acceptance of the returned signed XPI |

This candidate makes Answer Cadence the Settings-only flagship feature: one
draft/Apply transaction, a real structured-plan preview, a rhythm strip and
transport telemetry, 30–300 BPM presets and Custom controls, and one shared
plain/preview cadence scheduler. Firefox requires structured entry's score to
remain self-contained in the serialized MAIN-world function, so the build
compares its tuning with the shared score and rejects drift.

The release also incorporates the exact complex-radical and direct-assumption
fixes, safer symbolic input handling, synchronous insertion claiming,
consistent machine-form structured planning, detached-target checks, and the
pinned window/tab/frame/field/question/answer ownership invariant. The closed
findings remain covered by the passing suites and both isolated browser runs.

There is no permission, host, native-protocol, or data-collection change.
Cadence still acts only after validation and editor planning. It does not alter
answers, select targets, submit, check, advance, navigate, or claim concealment.
Synthetic input and MAIN-world editor interaction remain observable, and zero
footprint means no persistent extension-created state or UI in the visited
website. The browser gates used throwaway profiles and did not touch the
owner's Firefox or Hawkes session.

## Historical 0.38.0 audit

**Audited:** 3 September 2026

**Browser present:** Firefox 154.0.1

**Status:** Mozilla signed and installed, but not released. Physical acceptance
on 3 September 2026 found that pressing Solve again left the prior answer
visible during the retry. The signed 0.38.0 artifact is retained for audit but
must not be promoted; the correction begins the 0.38.1 source line.

The candidate and its recorded hash are frozen. No further packaged-source
edit or rebuild belongs to 0.38.0 unless AMO forces a change, in which case the
version and release evidence must be regenerated.

### 0.38.0 provenance ledger

| Record | Value |
|---|---|
| Candidate artifact | `ethnos-hawkes-0.38.0-unsigned.xpi` |
| Frozen candidate SHA-256 | `5308a5b1853b641050388e9d1be9d893def3d138bb1bd7c7f05140d353fdfdbf` |
| Mozilla-signed artifact | `ethnos-hawkes-0.38.0-mozilla-signed.xpi` |
| Mozilla-signed SHA-256 | `1adc0ef88015cc84811f2456f8f8a39054c1ec234ba4317940b973a6d2f82d3e` |
| Build-time repository base | `e3477fe6327e66fb8ef1a4d626929f1d6b4ab9b2` |
| Artifact-producing commit | None—the candidate was built from an uncommitted worktree, so inventing an ID would give false provenance |
| Verified artifact-source snapshot | `06397109f52c3dfa68115f5d96d57e4acee72611` |
| Post-freeze release-procedure commit | `384606c0067cbc17855b9943c7d3599d75ef4c83` |
| Public privacy/support documentation commit | `a463b50f17b56e78157941411c3a61bcab593b0e` |
| Candidate status | **not promoted—physical acceptance finding** |
| Installed signed state | Firefox `signedState: 2`, version 0.38.0, active |
| Remaining gate | Correct as 0.38.1 → rebuild and sign → repeat normal-Firefox physical acceptance |
| Promotion rule | Only the Mozilla-signed artifact that passes physical acceptance becomes released 0.38.0 |

Commit `0639710` was created after the build because the extension had never
been tracked. Before committing it, every one of the 28 XPI members was
byte-compared with its corresponding source file with zero mismatches. It is
therefore the first immutable, reproducible source snapshot for the candidate,
but it is deliberately not mislabeled as a historical artifact-producing
commit.

### 0.38.0 outcome

The extension, native companion boundary, installer, test protocol, privacy
notice, and release procedure now form one documented release path. The local
candidate is intentionally marked unsigned:

```text
dist/ethnos-hawkes-0.38.0-unsigned.xpi
SHA-256 5308a5b1853b641050388e9d1be9d893def3d138bb1bd7c7f05140d353fdfdbf
```

That unsigned file remains the byte-for-byte AMO input. Mozilla's returned
signed artifact is retained separately at
`dist/ethnos-hawkes-0.38.0-mozilla-signed.xpi`; it installed normally, but the
physical-acceptance finding prevents promotion to a released version.

### 0.38.0 verification completed

| Gate | Result |
|---|---|
| Full repository test suite | `568 passed` |
| Extension-specific validator | 28 packaged files validated |
| Python byte compilation | passed |
| Ruff on changed host/installer modules | passed |
| Reproducible XPI test | passed |
| XPI archive integrity | passed, 28 expected files |
| Native installer isolated install/check/uninstall test | passed |
| Installed native-host health request | passed end to end |
| `web-ext` 10.6.0 lint under Node 22.23.2 | 0 errors; one reviewed Android-only minimum-version warning |
| Mozilla unlisted signing and normal install | passed; signed artifact retained and hashed |
| Signed-browser physical acceptance | **failed:** a retry displayed the prior answer while solving |
| Firefox version vs minimum 140 | Firefox 154.0.1 satisfies it |

The generated native files are:

```text
~/.local/share/ethnos-hawkes/ethnos-hawkes-host
~/.mozilla/native-messaging-hosts/ethnos_hawkes.json
```

The launcher is generated atomically, the manifest authorizes only
`ethnos-hawkes@local`, and the health check exchanges a real length-prefixed
native message. Firefox was deliberately not restarted during the audit
because an existing browser session was in use.

### 0.38.0 hardening decisions

- One standing host scope: `*://learn.hawkeslearning.com/*`; no broad URL
  pattern and no declarative content script.
- No browser-network transport, remotely loaded code, request interception,
  automatic submission, navigation, or answer selection.
- Question text, MathML, and fallback images use only the native-messaging
  boundary and are accurately declared as Mozilla `websiteContent`.
- Exact markup is preferred. Screenshot fallback defaults to a question-only
  vertical crop and fails closed when safe bounds cannot be established.
- Coursework and screenshots are not retained by the extension. Diagnostic
  storage is bounded and redacted.
- Page access is one-shot. Solving leaves no persistent page node, attribute,
  style, listener, global, or exposed extension resource. User-requested
  insertion necessarily changes the Hawkes editor and is not claimed to be
  undetectable while it occurs.
- Insertion rechecks question identity, refuses ambiguous fields and unsupported
  templates, requires a separate user action, and never submits.
- Native installation no longer points Firefox at or deletes a launcher inside
  the source checkout. Install and uninstall target only two generated files.

### 0.38.0 live evidence

The existing Hawkes session verified the repaired structured and sidebar paths:

- `a^(11/12)` rendered with base `a` and exponent fraction `11/12` while page
  focus was on `BODY` and only one answer field was visible;
- `y*sqrt(30)/30` rendered with `y` outside the radical;
- insertion remained in the `Inserted` state rather than solving twice;
- no test action pressed Hawkes Submit.

See [Hawkes E2E proof](history/HAWKES_E2E_PROOF.md) and
[editor findings](HAWKES_EDITOR_FINDINGS.md) for the captured reasoning and
editor protocol.

### 0.38.0 physical-acceptance finding and next gate

The installed Mozilla-signed 0.38.0 panel correctly recognized Question 5,
Step 2 and produced `14`. Pressing Solve again began a real three-pass local
solve, but the panel continued to display `14` while reporting Solving. Even
though the answer happened to remain correct for that retry, presenting an old
result as current work is ambiguous and fails the professional-release bar.

Version 0.38.1 clears answer, recognized-problem, and source state at retry
start in both the event page and optimistic panel render. The independent panel
view also suppresses any answer carried by delayed running state. The remaining
gate is a new 0.38.1 package/sign/install cycle followed by the complete
existing-normal-Firefox protocol in `extension/TESTING.md`, without submitting
work during the acceptance actions.

Hawkes can change its private editor markup independently of this project, so
the live protocol remains a release gate for every version even when all local
tests pass. The permanent installation steps and rollback procedure are in
[`extension/RELEASE.md`](../extension/RELEASE.md).
