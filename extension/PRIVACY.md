# Privacy notice — Facet Hawkes Assistant

Last updated: 5 September 2026

## What is processed

When the user opens the assistant and starts a solve, it reads only the active
Hawkes question needed for that solve: instruction text and displayed MathML.
If the page states no mathematics the solvers can read, it may capture a
cropped image of the question instead. By default the crop begins at the
question instruction and ends before the answer area, excluding page
header/account UI and the answer controls. If those boundaries cannot be
established, the solve fails without sending an image. A user may explicitly
disable that limit for an unusual layout, in which case the visible viewport is
processed. Firefox classifies this material as **website content**.

The add-on sends that question material through Firefox native messaging to
the locally installed `ethnos_hawkes` companion. That name is the registered
native-messaging identifier and is shown nowhere in the interface. Mozilla
treats transfer to a native companion as data transmission even when it remains
on the same computer, so the manifest declares the required `websiteContent`
category.

## Where it goes

- Every question the page states as mathematics goes to Facet, which decides
  how it is answered: exact mathematics first and without a model, a reasoning
  model only for what those decline, and a parabola or quadratic-regression
  specialist for a graph. What is sent is the instruction and the exact
  MathML-derived expressions, and never a screenshot. Graph requests also carry
  normalized bounds and snap spacing; DOM and control identifiers remain in
  Firefox. SVG regression requests send the instruction and exact point
  coordinates instead of a MathML expression. The browser chooses no
  destination, model, or device.
- The companion reaches Facet over SSH to the one host it is configured for.
  With the default configuration that host is this computer, so the material
  does not leave it. A configuration pointing elsewhere sends the question
  material to that host.
- Only a question the page draws as a picture rather than stating as
  mathematics falls back to image transcription, which uses the Ollama endpoint
  the companion is configured for. With the default loopback endpoint,
  processing stays on this computer. A user-configured remote endpoint receives
  the question material.
- The browser add-on contains no analytics, advertising, telemetry, or HTTP
  transport and sends nothing to the developer.

## Storage and retention

- A completed answer card is held in Firefox's memory-only `storage.session`
  so it can survive the non-persistent event page being unloaded while the
  toolbar popup is closed. It is shown again only after the active tab's
  question signature matches, and Firefox clears it when the browser session
  ends. It is never written to `storage.local` or to diagnostics.
- Screenshots are not stored by the extension.
- Browser-originated screenshots and transcriptions use a temporary directory
  that is removed when the native-host request finishes.
- `storage.local` contains preferences and a bounded diagnostic ring only.
  Diagnostic payloads redact question text, answers, screenshots, and profile
  identifiers. The user can clear the ring in Settings.
- The configured Ollama service may have its own logging or retention policy;
  that is controlled by the operator of that endpoint.

## Website effects

Reading and solving add no persistent node, attribute, style, listener, page
global, or extension resource to Hawkes. Insertion occurs only after the user
presses **Insert** and necessarily changes Hawkes' answer editor. Synthetic
input and the structured editor calls can be observed by page code while the
insertion occurs. Answer Cadence additionally emits a transient, one-way DOM
presentation cue containing a note index and elapsed time. Page code can observe
or forge that cue; it cannot command insertion or any other action. Its listener
is removed after the performance. Local music runs in Web Audio inside the
extension, with no network, native host or model, and scores are not retained.
Answer Cadence does not claim or seek
human-like trusted input, anti-detection, fingerprint avoidance, or
undetectability. Zero footprint means no persistent extension-created page UI
or state after the operation, not invisible activity during insertion. The
cadence model and its safety boundary are documented in the
[`Answer Cadence` design note](../docs/ANSWER_CADENCE.md).

## User control

The user can cancel a solve, disable automatic solving, clear diagnostics, or
remove the add-on at any time. Removing the separately installed native host
registration prevents all companion communication. The add-on never submits,
checks, or advances a question.
