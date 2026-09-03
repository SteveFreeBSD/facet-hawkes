# Project operating rules

## Live Firefox and Hawkes testing

- Read `docs/HAWKES_DEVELOPMENT_FLOW.md` before any browser action. Its mode A
  is the default whenever the owner has a real Hawkes session open.
- The owner's extension-testing workflow uses a **direct Hawkes login**. It
  does not use OSUIT Canvas, a school portal, CAS/SSO, or an LMS redirect.
- Never infer an authentication route from Firefox history. In particular, do
  not open Canvas course or assignment URLs to start a Hawkes test.
- Do not navigate, restart, close, or open Firefox during a live session unless
  the owner explicitly requests that exact action. Attach to the existing
  session when inspection is requested; do not create another browser profile
  or competing Firefox instance.
- Start existing-session work with
  `python3 scripts/inspect_live_firefox.py inspect`. It captures the one current
  Firefox window and restores focus; it does not launch, navigate, or automate
  the page. Delete its temporary screenshot after inspection.
- `scripts/live_browser.py` and `scripts/run_extension_harness.py` are isolated
  Marionette harnesses. Do not start them during an owner's live Firefox
  session or use their results as signed-artifact physical acceptance.
- If a live Hawkes page is required, ask the owner to sign in directly and
  navigate to the intended practice question. Never handle school or Hawkes
  credentials.
- Live acceptance is non-submitting: the extension may inspect, solve, and
  insert only when requested, but neither an agent nor the extension may press
  Hawkes Submit/Check/Next as part of a smoke test.
- While a panel says Solving, inspect the native-host process and wait. Do not
  click Solve again; that control becomes Cancel while work is running.
- "Zero footprint" means no persistent extension-created state or UI in the
  visited website. It is not a claim of undetectability; see
  `extension/README.md` and `extension/PRIVACY.md`.
