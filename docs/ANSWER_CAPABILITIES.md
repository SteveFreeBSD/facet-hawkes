# What Facet can answer, and what Hawkes Assistant can enter

Read this before adding an exact solver family to `facet-runtime`.

The recurring defect this page exists to end: a new exact family is added, Facet
answers correctly, and only afterwards -- live, on the owner's coursework -- is
it found that the add-on cannot enter that shape of answer. It has happened to
the vertex (a pair the page brackets), the distance (a radical), the quadrant (a
chosen alternative), and the midpoint (a pair of *rationals*). Each time both
halves looked finished, because each half was.

**Facet owns what the answer is. Hawkes Assistant owns how it is entered.** The
failures are never in either half. They are in a *composition* neither half
names: `(1,-4)` was enterable and `17/2` was enterable and `(17/2,-1/2)` was not.

So a family is not finished when Facet returns the right value. It is finished
when this table has a row saying how that value is entered, or saying plainly
that it cannot be.

## The wire

Every exact answer now carries `answer.form` -- one of `scalar`,
`ordered-pair`, `parts`, `choice` -- beside `entry_mode`. It is deliberately the
*family* and not a description of the value: what notation a value is written in
stays readable from the value, and what a consumer cannot cheaply recover is
which of these it is holding. Plans are not values and keep their own `kind`
(`parabola_plan`, `point_plot_plan`, `quadratic_regression`).

`ANSWER_FORMS` in `facet_runtime.exact.router` is the closed set. Growing it is a
protocol change, and `tests/test_answer_capabilities.py` here fails until this
table has a row for the new member.

## The map

Physical topology is what the page publishes; the insertion mechanism is the
function that does the typing.

| Semantic answer | Canonical form | `form` | Hawkes logical shape | Physical topology | Insertion mechanism | Unit-tested | Harness | Live-proven |
|---|---|---|---|---|---|---|---|---|
| scalar integer | `42` | `scalar` | field | one dynamic or plain box | `planEntry` → `enterPlan` | yes | yes | yes |
| scalar rational | `17/2` | `scalar` | field | one box, Fraction template | `planEntry` → Fraction template | yes | no | yes |
| scalar rational, no template | `17/2` | `scalar` | field | one drawn box, `pairedControl` | `planFractionBySlash` → `slash` step | yes | no | yes |
| radical | `sqrt(101)`, `10*sqrt(2)` | `scalar` | field | one box, Radical template | `planRun` → `Radical` / `IndexedRadical` | yes | no | yes |
| symbolic / exponent | `y^(23/20)` | `scalar` | field | one box, Exponent template | `planRun` → `Exponent` | yes | no | yes |
| named phrase | `Not a Real Number` | `choice` | option | radio group | **not typed** — the reader selects | yes | no | yes |
| ordered pair, integer components | `(1,-4)` | `ordered-pair` | field | page draws `( [box] )`, no PBrace | `pageBracketedPair` → `planAnswerParts` | yes | no | yes |
| ordered pair, integer components | `(2,3)` | `ordered-pair` | field | one box, PBrace template | `planRun` → `PBrace` group | yes | no | yes |
| **ordered pair, rational components** | `(17/2,-1/2)` | `ordered-pair` | field | one box, PBrace **and** Fraction | `planCommaList` → `PBrace` + `Fraction` per component | yes | no | yes |
| multipart scalars | `-3`, `3` | `parts` | multi | several drawn boxes | `planAnswerParts` → `enterPlainAnswerParts` | yes | yes | yes |
| multipart, one box, comma | `-3, 3` | `parts` | field | one box accepting `,` | `commaAnswerPlan` → `enterPlan` | yes | no | yes |
| table integer | `0`, `64` | `parts` | multi (table) | one control per blank cell | `enterTableCells` | yes | yes | yes |
| table rational / fraction | `2\sqrt{2}`, `-3/2` | `parts` | multi (table) | cell expands to numerator + denominator | `enterTableCells` → native `/` expansion | yes | yes | yes |
| choice / radio | `Quadrant IV` | `choice` | option | one radio group, N buttons | **not typed** — matched to a published label, the reader clicks | yes | no | yes |
| graph parabola | plan, no value | *plan* | graph | vertex + two symmetric controls | `graphOperation` | yes | no | yes |
| graph literal points | plan, no value | *plan* | graph | one draggable control per point | `graphOperation` (space plots) | yes | no | yes |

**Unit-tested** means a QuickJS or Python test drives the real module.
**Harness** means `scripts/run_extension_harness.py` exercises it in a real
Firefox — it has no native host, so it proves injection and reading, never a
solve. **Live-proven** means it has been observed working in the owner's own
session, through the retained ledger or the observatory.

## Unsupported compositions

Named rather than discovered. Each is refused cleanly today; none is silently
mis-entered.

| Composition | Why | What happens now |
|---|---|---|
| `parts` of ordered pairs | Several coordinate pairs, one per box. `planAnswerParts` plans each part with `planEntry`, so each pair needs its own bracketing route; nothing has verified the pairing against a multi-control page. | Planned per part; unproven live. Treat as unsupported until observed. |
| ordered pair with a radical component | `(sqrt(2),1)` needs Radical inside PBrace. `planRun` supports it structurally; no question has asked for it. | Plans; unproven. |
| nested fraction | `(1/2)/3` | `splitFraction` refuses more than one top-level slash. |
| decimal anything | `(8.5,-0.5)` | Refused: `.` is in no observed answer box's character set. This is the correct refusal — the exact form is the answer. |
| choice answer typed into a field | — | `answerFitsEditor` returns `editor-option-answer`; selecting stays the reader's action, always. |
| plan carrying a value | — | Refused at the protocol: a plan result carries only a plan. |
| interval notation with ∞ / ∪ | `(-∞,-3)∪(3,∞)` | `validateAnswer` refuses the characters; publishable as a reading, not insertable. |

## Adding a family

1. Emit the answer with the right `form`. Add a row to
   `facet-runtime/tests/test_answer_forms.py`.
2. Add a row here: the canonical form, the topology, the mechanism.
3. If there is no mechanism, add a row to *Unsupported compositions* instead and
   say what happens when the answer arrives.
4. `tests/test_answer_capabilities.py` reads this file and fails if a `form`
   has no row in either table.

The point of step 3 is that "unsupported" is a finished state. What is not a
finished state is discovering it live.

## See also

- [The Ethnos-Facet boundary](FACET_BRIDGE.md) — the protocol these answers cross
- [Retained failure ledger](FAILURE_LEDGER.md) — where an uninsertable answer shows up
- [Hawkes editor findings](HAWKES_EDITOR_FINDINGS.md) — what the page publishes
