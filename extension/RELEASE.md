# Firefox release runbook

This runbook produces a Mozilla-signed add-on that installs permanently in a
normal Firefox profile. A locally built XPI is unsigned and is only a release
candidate; do not weaken Firefox signature enforcement to install it.

## 0.46.0 candidate — prepared for publication approval

0.46.0 is the RC5-Cadence source line. It includes the 0.45.0 data-table route,
the 0.45.1 labelled-pair correction, and the complete Answer Cadence described
in the changelog. The local candidate passed the package, repository,
Mozilla-lint, reproducibility, and clean-profile unsigned-XPI gates on
6 September 2026, against the packaged source as it stood that day:

```text
dist/facet-hawkes-0.46.0-unsigned.xpi
SHA-256 6bf24fb9744da4b375171530cee9d0c2069a0e7c4be3536161ad6bd983215d64
33 packaged files, built twice from unchanged sources with the same digest
```

**That digest is evidence about that build, not about the working tree.** The
0.46.0 source line has advanced since the audit -- drawn-box fractions, radio
groups, point plotting and the transport change all landed after it -- so a
rebuild today produces a different digest and a different file count, and
should. A version is signed against a *fresh* run of the gates, with its own
digest recorded here. Re-derive the current one before quoting any number:

```console
$ uv run python scripts/build_extension.py
$ sha256sum dist/facet-hawkes-0.46.0-unsigned.xpi
```

The 0.46.0 publication strategy keeps the
existing sibling repositories, fixes `facet-runtime` at companion commit
`a83546e3aa5dd5dd347a054d791dd8a1a7925821`, and establishes
`SteveFreeBSD/facet-hawkes` as the canonical public Hawkes repository. The old
Ethnos repository is not a publication target; `ethnos-caspian` may remain as a
legacy/private remote. CI checks out the exact runtime commit rather than a
moving branch.

Do not submit yet. The runtime commit must be pushed to its existing public
repository, the canonical Hawkes repository must be created and populated, and
a fresh public sibling clone must pass before tagging or AMO submission. Each
external action requires the owner's explicit approval. Once the repository is
public, the add-on guide and privacy notice will be available at the canonical
repository under `extension/README.md` and `extension/PRIVACY.md`. The full
evidence and publication state are in the
[release audit ledger](../docs/HAWKES_RELEASE_AUDIT.md).

These identifiers deliberately do **not** change with the product name, and a
review that flags them as leftovers is wrong:

- the add-on ID `ethnos-hawkes@local`, which Firefox keys the installation and
  its `storage.local` to — renaming it orphans the profile;
- the native-messaging host `ethnos_hawkes` and the launcher the installer
  writes to `~/.local/share/ethnos-hawkes/`, which are already registered on
  disk;
- the wire value `solve_engine="ethnos"`, which names the companion's own image
  path in the native protocol.

None of them is shown anywhere in the interface.

## Superseded: frozen 0.43.0 candidate

Kept as the record of the last accepted candidate. It is superseded by 0.46.0
and must not be uploaded as the current one:

```text
dist/ethnos-hawkes-0.43.0-unsigned.xpi
SHA-256 3c19a69b41af3a82ab4ef1f2723da9b6b637ac37bb1419d8bf2eb966ef597001
```

The candidate contains 30 packaged files and was built twice from unchanged
sources with the same digest. Its product baseline is `bb1e66a`, which finishes
Answer Cadence and includes the recent exact-math, insertion-consistency, and
window-ownership hardening in its ancestry.

0.43.0 changes no permission, host, native protocol, or data-collection
declaration. Answer Cadence remains post-validation presentation timing: its
draft/Apply workflow and local Settings preview cannot alter an answer, editor
plan, target, or insertion policy. The preview shares the plain insertion score
and scheduler; the validator prevents its MAIN-world structured copy from
drifting. Synthetic input and MAIN-world editor calls remain page-observable,
and zero footprint still means no persistent extension-created website state.

Completed local gates: 168 focused cadence/extension tests, 349 Hawkes-focused
tests, 825 repository tests, Ruff check and format, three documentation/link
checks, the 30-file repository validator, isolated Firefox harness 17/17,
Settings browser smoke 17/17, `web-ext lint --warnings-as-errors` at 0 errors /
0 warnings / 0 notices, archive integrity, and an identical rebuild. Mozilla
signing and physical acceptance of the returned signed XPI in the owner's
normal Firefox remain external gates. Neither isolated browser run touched the
owner's profile or Hawkes session.

## Prior 0.42.0 candidate

The prior accepted local candidate is retained for audit and rollback context;
it is superseded by 0.43.0 and must not be uploaded as the current candidate:

```text
dist/ethnos-hawkes-0.42.0-unsigned.xpi
SHA-256 3937c19699e0284acc901f8d86cd6a0086c4da099223be459ad4a7a3f5684df5
```

0.39.0 through 0.41.4 were development builds and must not be uploaded. The
last signed release is retained for rollback:

```text
signed     bd61a7d54aca41af9bb8-0.39.2.xpi
SHA-256    88b6a002b877450601f7f03c1e462d2bcfb379a1a0b84266e040da5aa6670d26
candidate  dist/ethnos-hawkes-0.39.2-unsigned.xpi
SHA-256    57e0ac32081a038110b2ac5d439b26035fe074e522131ebe01523cbbb3fe55b7
```

Completed gates on the historical 0.42.0 candidate were: repository validator,
653 tests,
`web-ext lint --warnings-as-errors` at 0 errors / 0 warnings / 0 notices, and an
identical rebuild. The real-browser harness and signed-artifact physical
acceptance remain release gates; neither is replaced by the local checks.

Documentation-only updates do not change that archive. If any packaged file
must change, bump the version, rerun every gate, and record a new candidate
hash rather than silently replacing this artifact.

## 1. Preflight

From the repository root, with the working tree intentionally reviewed:

```console
$ uv sync
$ uv run pytest
$ python3 scripts/build_extension.py --check
$ python3 deploy/firefox/install_native_host.py --write
$ python3 deploy/firefox/install_native_host.py --check
```

Mozilla's current documentation covers **web-ext 10**, which since March 2026
requires Node.js 22 or newer. On the signing machine, install the current
release and run Mozilla's official validator with warnings treated as errors:

Node is not installed system-wide on the development host, and the gate needs
no root. Install both under `~/.local`:

```console
$ curl -O https://nodejs.org/dist/latest-v22.x/node-v22.23.2-linux-x64.tar.xz
$ curl -O https://nodejs.org/dist/latest-v22.x/SHASUMS256.txt
$ grep ' node-v22.23.2-linux-x64.tar.xz$' SHASUMS256.txt | sha256sum -c -
$ tar -xJf node-v22.23.2-linux-x64.tar.xz -C ~/.local/opt
$ export PATH="$HOME/.local/opt/node-v22.23.2-linux-x64/bin:$HOME/.local/bin:$PATH"
$ npm install -g --prefix ~/.local web-ext
$ web-ext --version
$ release_lint_dir=$(mktemp -d)
$ unzip -q dist/facet-hawkes-0.46.0-unsigned.xpi -d "$release_lint_dir"
$ web-ext lint --source-dir "$release_lint_dir" --warnings-as-errors
```

The repository validator enforces project-specific invariants. `web-ext lint`
and the AMO upload validator remain separate gates. Unpacking the candidate XPI
ensures the official lint gate examines exactly the files intended for
submission — 33 for 0.46.0 — rather than documentation or another rebuild. Fix
every error; review any warning before proceeding.

Confirm all of the following:

- `extension/manifest.json` has the intended new three-part version.
- `extension/CHANGELOG.md` has a matching top entry.
- the fixed ID is `ethnos-hawkes@local` in both the add-on and native manifest;
- `websiteContent` accurately describes the native-messaging transfer;
- [`PRIVACY.md`](PRIVACY.md) matches the configured Ollama endpoint;
- the isolated harness and Settings smoke in [`TESTING.md`](TESTING.md) pass;
- the signed-artifact live checks pass without submitting work, including
  exact solve, plain and structured insertion, next-step reset, duplicate and
  wrong-window guards, cadence timing, and removal footprint.

## 2. Build the candidate

```console
$ python3 scripts/build_extension.py
```

The output is `dist/facet-hawkes-<version>-unsigned.xpi` plus a SHA-256 digest.
Before the candidate is frozen, re-running the build from unchanged packaged
sources must print the same digest. Once frozen, keep that exact candidate and
digest together and do not rebuild before submission.

## 3. Obtain Mozilla's signature

Use the [AMO Developer Hub](https://addons.mozilla.org/developers/) and choose
self-distribution/unlisted signing. Upload the unsigned candidate, use the
fixed add-on ID, provide the privacy-policy URL, and resolve every automated or
human review finding. Download the signed XPI returned by Mozilla; do not rename
the unsigned candidate as though it were signed.

`web-ext sign --channel=unlisted` supports initial unlisted submissions after
creating AMO API credentials. For this already-frozen byte-for-byte candidate,
use the Developer Hub upload path so there is no second packaging step. Keep
any API secret out of the repository, shell history, logs, and release
artifacts. Mozilla's current commands and requirements are documented in the
[web-ext command reference](https://extensionworkshop.com/documentation/develop/web-ext-command-reference/).

Inspect the downloaded file before installation:

```console
$ unzip -t path/to/mozilla-signed.xpi
$ unzip -p path/to/mozilla-signed.xpi manifest.json | python3 -m json.tool
$ sha256sum path/to/mozilla-signed.xpi
```

The manifest version and ID must match the candidate. The signed archive will
contain Mozilla signature metadata under `META-INF/`, and its SHA-256 will
naturally differ from the unsigned candidate. Retain both artifacts and both
hashes in the release record.

## Historical signed 0.39.2 artifact

Mozilla returned the signed archive on 3 September 2026. Both artifacts and
both hashes are retained together, as this runbook requires:

```text
candidate  dist/ethnos-hawkes-0.39.2-unsigned.xpi
SHA-256    57e0ac32081a038110b2ac5d439b26035fe074e522131ebe01523cbbb3fe55b7

signed     bd61a7d54aca41af9bb8-0.39.2.xpi
SHA-256    88b6a002b877450601f7f03c1e462d2bcfb379a1a0b84266e040da5aa6670d26
```

Verified against the candidate: the same 28 files, plus signature metadata
under `META-INF/` (`cose.manifest`, `cose.sig`, `manifest.mf`, `mozilla.sf`,
`mozilla.rsa`). Every packaged file is byte-identical except `manifest.json`,
which AMO returns with its trailing newline stripped — one byte, and
semantically the same document. Version, id, minimum version and the
`websiteContent` declaration all match what was submitted.

Historical status: **candidate, pending physical acceptance.** The live checks
below had not yet run against that artifact when this record was written.

## 4. Permanent installation

Physical acceptance uses the owner's **direct Hawkes login**. Never start a
release test through OSUIT Canvas, a school portal, CAS/SSO, or an LMS redirect,
and never reconstruct a login route from Firefox history. The owner signs in
and opens the intended practice question before browser testing begins.
Use the existing-session mode in
[`docs/HAWKES_DEVELOPMENT_FLOW.md`](../docs/HAWKES_DEVELOPMENT_FLOW.md); do not
substitute the separate Marionette profile for signed-artifact acceptance.

1. Restart Firefox after installing or changing the native host.
2. Open `about:addons`, choose the gear menu, then **Install Add-on From File**.
3. Select the Mozilla-signed XPI—not the `*-unsigned.xpi` candidate.
4. Accept the Hawkes-site and website-content disclosures.
5. Open the add-on's Settings and run **Test connection**.
6. Confirm the current Firefox window and signed add-on with
   `python3 scripts/inspect_live_firefox.py inspect`.
7. After the owner has directly opened the Hawkes practice question, run the
   manual smoke checks in `TESTING.md`: exact solve, screenshot refusal
   or fallback, plain insertion, structured insertion, next-question reset,
   duplicate-insertion guard, and removal footprint. Never press Hawkes submit
   as part of the extension smoke test.

Only after the signed XPI passes this physical-browser acceptance is a version
**released**. 0.46.0 is a locally validated unsigned candidate awaiting the
approved runtime-first publication and fresh-clone verification described
above. 0.43.0 reached **release candidate complete** and was superseded before
signing.

Firefox Release and Beta require Mozilla-signed extensions. Mozilla documents
both listed and unlisted distribution in its
[signing overview](https://extensionworkshop.com/documentation/publish/signing-and-distribution-overview/)
and the Add-ons Manager flow in
[Installing self-distributed add-ons](https://extensionworkshop.com/documentation/publish/install-self-distributed/).

## 5. Upgrade, rollback, and removal

- Upgrade by signing a strictly higher version and installing that signed XPI.
- Roll back by reinstalling a previously retained signed XPI with a compatible
  native protocol. Firefox may require removing the newer version first.
- Remove the add-on from `about:addons`.
- Remove the native registration separately with:

  ```console
  $ python3 deploy/firefox/install_native_host.py --uninstall --write
  ```

The installer removes only its generated manifest and launcher. It does not
delete this checkout, models, course data, Firefox profiles, or visited-site
data.
