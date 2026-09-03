# Firefox release runbook

This runbook produces a Mozilla-signed add-on that installs permanently in a
normal Firefox profile. A locally built XPI is unsigned and is only a release
candidate; do not weaken Firefox signature enforcement to install it.

## Frozen 0.40.3 candidate

The accepted local candidate is frozen. Do not rebuild or alter packaged
source before submission unless AMO requires a source change:

```text
dist/ethnos-hawkes-0.40.3-unsigned.xpi
SHA-256 81053aa29ff2473d18300a378738401a89582a7c7c0bbe04e80b62a5cf697f4b
```

0.39.0 through 0.40.2 were development builds and must not be uploaded. The
last signed release is retained for rollback:

```text
signed     bd61a7d54aca41af9bb8-0.39.2.xpi
SHA-256    88b6a002b877450601f7f03c1e462d2bcfb379a1a0b84266e040da5aa6670d26
candidate  dist/ethnos-hawkes-0.39.2-unsigned.xpi
SHA-256    57e0ac32081a038110b2ac5d439b26035fe074e522131ebe01523cbbb3fe55b7
```

0.40.3 changes no permission, host, or data-collection declaration. Gates on
this candidate: repository validator, 633 tests,
`web-ext lint --warnings-as-errors` at 0 errors / 0 warnings / 0 notices, an
identical rebuild, and 11 of 11 checks in the real-browser harness.

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
$ unzip -q dist/ethnos-hawkes-0.40.3-unsigned.xpi -d "$release_lint_dir"
$ web-ext lint --source-dir "$release_lint_dir" --warnings-as-errors
```

The repository validator enforces project-specific invariants. `web-ext lint`
and the AMO upload validator remain separate gates. Unpacking the frozen XPI
ensures the official lint gate examines the exact 28 files intended for
submission, rather than documentation or another rebuild. Fix every error;
review any warning before proceeding.

Confirm all of the following:

- `extension/manifest.json` has the intended new three-part version.
- `extension/CHANGELOG.md` has a matching top entry.
- the fixed ID is `ethnos-hawkes@local` in both the add-on and native manifest;
- `websiteContent` accurately describes the native-messaging transfer;
- [`PRIVACY.md`](PRIVACY.md) matches the configured Ollama endpoint;
- the live checks in [`TESTING.md`](TESTING.md) pass without submitting work.
  Checks 8, 9 and 10 are new in 0.39.0 and are the ones this version turns on:
  a placed answer clearing for the next **step**, the unread-instruction
  caution, and two windows not fighting. Checks 8 and 10 cover fixes that are
  verified by unit test but **not yet confirmed against a live browser**, and
  both fail silently, so neither may be skipped.

## 2. Build the candidate

```console
$ python3 scripts/build_extension.py
```

The output is `dist/ethnos-hawkes-<version>-unsigned.xpi` plus a SHA-256 digest.
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

## Signed 0.39.2 artifact

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

Status: **signed, pending physical acceptance.** The live checks below have not
yet run against this artifact.

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

Only after the signed XPI passes this physical-browser acceptance is 0.40.3
**released**. Until then its status remains **release candidate complete**.

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
