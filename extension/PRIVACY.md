# Privacy notice — Ethnos Hawkes Assistant

Last updated: 3 September 2026

## What is processed

When the user opens the assistant and starts a solve, it reads only the active
Hawkes question needed for that solve: instruction text and displayed MathML.
If the exact solver cannot handle that markup, it may capture a cropped image
of the question. By default the crop begins at the question instruction and
ends before the answer area, excluding page header/account UI and the answer
controls. If those boundaries cannot be established, the solve fails without
sending an image. A user may explicitly disable that limit for an unusual
layout, in which case the visible viewport is processed. Firefox classifies
this material as **website content**.

The add-on sends that question material through Firefox native messaging to
the locally installed `ethnos_hawkes` companion. Mozilla treats transfer to a
native companion as data transmission even when it remains on the same
computer, so the manifest declares the required `websiteContent` category.

## Where it goes

- Exact MathML problems are processed in the local companion without a model
  request.
- Image transcription and model fallback use the Ollama endpoint configured in
  Ethnos. With the default loopback endpoint, processing stays on this
  computer. A user-configured remote endpoint receives the question material.
- If the user explicitly selects **Facet (experimental)**, the instruction and
  exact MathML-derived expression are sent over SSH to the fixed `casbox`
  machine on the local network. No screenshot is sent through this path.
- The browser add-on contains no analytics, advertising, telemetry, or HTTP
  transport and sends nothing to the developer.

## Storage and retention

- Coursework text, answers, and screenshots are not stored by the extension.
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
insertion occurs; the add-on does not claim to be undetectable.

## User control

The user can cancel a solve, disable automatic solving, clear diagnostics, or
remove the add-on at any time. Removing the separately installed native host
registration prevents all companion communication. The add-on never submits,
checks, or advances a question.
