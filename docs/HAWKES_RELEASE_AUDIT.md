# Ethnos Hawkes Assistant 0.38.0 release audit

**Audited:** 3 September 2026

**Browser present:** Firefox 154.0.1

**Status:** release candidate is built and locally verified; Mozilla signing
and the post-signature browser smoke test remain external release gates.

The candidate and its recorded hash are frozen. No further packaged-source
edit or rebuild belongs to 0.38.0 unless AMO forces a change, in which case the
version and release evidence must be regenerated.

## Provenance ledger

| Record | Value |
|---|---|
| Candidate artifact | `ethnos-hawkes-0.38.0-unsigned.xpi` |
| Frozen candidate SHA-256 | `5308a5b1853b641050388e9d1be9d893def3d138bb1bd7c7f05140d353fdfdbf` |
| Build-time repository base | `e3477fe6327e66fb8ef1a4d626929f1d6b4ab9b2` |
| Artifact-producing commit | None—the candidate was built from an uncommitted worktree, so inventing an ID would give false provenance |
| Verified artifact-source snapshot | `06397109f52c3dfa68115f5d96d57e4acee72611` |
| Post-freeze release-procedure commit | `384606c0067cbc17855b9943c7d3599d75ef4c83` |
| Public privacy/support documentation commit | `a463b50f17b56e78157941411c3a61bcab593b0e` |
| Candidate status | **release candidate complete** |
| Remaining gate | Mozilla signing → normal Firefox install → documented non-submitting physical acceptance |
| Promotion rule | Only the Mozilla-signed artifact that passes physical acceptance becomes released 0.38.0 |

Commit `0639710` was created after the build because the extension had never
been tracked. Before committing it, every one of the 28 XPI members was
byte-compared with its corresponding source file with zero mismatches. It is
therefore the first immutable, reproducible source snapshot for the candidate,
but it is deliberately not mislabeled as a historical artifact-producing
commit.

## Outcome

The extension, native companion boundary, installer, test protocol, privacy
notice, and release procedure now form one documented release path. The local
candidate is intentionally marked unsigned:

```text
dist/ethnos-hawkes-0.38.0-unsigned.xpi
SHA-256 5308a5b1853b641050388e9d1be9d893def3d138bb1bd7c7f05140d353fdfdbf
```

That file is suitable for temporary development loading or AMO upload. It is
not represented as permanently installable in Firefox Release; Mozilla must
sign it first.

## Verification completed

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

## Hardening decisions

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

## Live evidence

The existing Hawkes session verified the repaired structured and sidebar paths:

- `a^(11/12)` rendered with base `a` and exponent fraction `11/12` while page
  focus was on `BODY` and only one answer field was visible;
- `y*sqrt(30)/30` rendered with `y` outside the radical;
- insertion remained in the `Inserted` state rather than solving twice;
- no test action pressed Hawkes Submit.

See [Hawkes E2E proof](HAWKES_E2E_PROOF.md) and
[editor findings](HAWKES_EDITOR_FINDINGS.md) for the captured reasoning and
editor protocol.

## Remaining release gates

1. On the signing environment, install web-ext 10 under Node.js 22 or newer and
   run official `web-ext lint --warnings-as-errors` against an unpacked copy of
   the frozen candidate. Node and npm are not installed on this machine, so
   this was not silently substituted with the repository validator.
2. Upload that exact frozen candidate for AMO unlisted/self-distributed
   signing, provide the published privacy-policy URL, and resolve AMO
   validation/review findings. `web-ext sign` supports initial unlisted
   submissions, but Developer Hub upload avoids repackaging this frozen file.
3. Restart Firefox, install the Mozilla-signed result through `about:addons`,
   record its separate SHA-256, and run **Test connection**.
4. Run the complete manual protocol in `extension/TESTING.md`, especially the
   new fail-closed screenshot-region check, against a permitted practice
lesson without submitting work.

0.38.0 is called **released** only after those signed-artifact physical
acceptance checks pass. Its current state is **release candidate complete**.

Hawkes can change its private editor markup independently of this project, so
the live protocol remains a release gate for every version even when all local
tests pass. The permanent installation steps and rollback procedure are in
[`extension/RELEASE.md`](../extension/RELEASE.md).
