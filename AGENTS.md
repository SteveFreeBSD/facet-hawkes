# Project operating rules

## Live Firefox and Hawkes testing

- The owner's extension-testing workflow uses a **direct Hawkes login**. It
  does not use OSUIT Canvas, a school portal, CAS/SSO, or an LMS redirect.
- Never infer an authentication route from Firefox history. In particular, do
  not open Canvas course or assignment URLs to start a Hawkes test.
- Do not navigate, restart, close, or open Firefox during a live session unless
  the owner explicitly requests that exact action. Attach to the existing
  session when inspection is requested; do not create another browser profile
  or competing Firefox instance.
- If a live Hawkes page is required, ask the owner to sign in directly and
  navigate to the intended practice question. Never handle school or Hawkes
  credentials.
- Live acceptance is non-submitting: the extension may inspect, solve, and
  insert only when requested, but neither an agent nor the extension may press
  Hawkes Submit/Check/Next as part of a smoke test.
- "Zero footprint" means no persistent extension-created state or UI in the
  visited website. It is not a claim of undetectability; see
  `extension/README.md` and `extension/PRIVACY.md`.
