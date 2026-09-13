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

Every exact answer carries `answer.form` -- one of `scalar`, `ordered-pair`,
`parts`, `choice`, `relation` -- beside `entry_mode`. It is deliberately the
*family* and not a description of the value: what notation a value is written in
stays readable from the value, and what a consumer cannot cheaply recover is
which of these it is holding. Plans are not values and keep their own `kind`
(`parabola_plan`, `point_plot_plan`, `quadratic_regression`).

`ANSWER_FORMS` in `facet_runtime.exact.router` is the closed set, and growing it
is a protocol change.

## An equation has two entry paths, and the page picks

`relation` is the one family whose answer is not a value. "Find the equation of
the line in slope-intercept form" is answered `y = -2x + 5`, and Hawkes takes
that two ways:

| The page | What it takes | Classified as |
|---|---|---|
| a bare box | the whole equation, `y=-2x+5` | `relation/…` |
| a box it prints `f(x) =` in front of | the right side, `-5x-3` | `scalar/…` |

So one answer presents two compositions, and both have to have a way in. The
right side is classified as a `scalar` because that is exactly what it is once
the page has stated the subject: same planner route, same rows, and those rows
already existed -- `scalar-plain` and `scalar-fraction-group` are the two it
lands on.

**Which path a page takes is read, never assumed.** `surfaceStatesSubject` in
`common/editor-rules.js` decides it from two facts, either of which is enough:
the subject `inspectField` finds printed in front of the box, and whether the
box's own published characters include an equals sign. Two signals for one fact,
so that a layout change that stopped the label being readable cannot silently
start typing a whole equation into a box that already holds half of it.

Until 2026-09-09 there was no such reading. The runtime returned the right side
alone, which is an answer only on the second kind of page, and lesson 2.4's bare
box refused it as an incorrect format. The defect was not in either half: Facet
had the line right and the add-on entered what it was given.

## The authority

**`docs/answer-capabilities.json` is the authority, and this page is rendered
from it.** Four `form` values were never fine-grained enough to be a gate: a new
solver rarely adds a form, it adds a *notation* under one that already has a
row, and `ordered-pair` having a row said nothing about whether an
`ordered-pair` of rationals could be typed.

So the unit is the **composition** -- the form, plus the structural features of
the value that decide which planning route it takes. `planEntry` branches on
exactly those: a bracketed pair, then a top-level fraction, then a run of
templates for exponents, radicals, groups and absolute values.

`tests/test_answer_compatibility.py` runs the authority rather than reading it.
Every declared composition is produced by a real solver, rendered by the host's
own entry rule, and handed to the shipped planner under QuickJS against the page
topology its row names. Every *unsupported* row is driven the same way and has
to be refused by the code it declares. For closure, the gate observes every
exact answer constructed by `facet-runtime`'s own test suite, using those tests
as the maintained emitter probes rather than copying their mathematics here.
It also keeps the sweep of thirty-seven real lesson questions as independent
live-course coverage. Either source fails on a composition nothing has
declared.

Edit the JSON, then:

```console
$ python3 scripts/render_answer_capabilities.py --write
```

## The map

Physical topology is what the page publishes; the insertion mechanism is the
function that does the typing.

<!-- generated:supported -->
| Semantic answer | `form` | Notation | Example | Physical topology | Insertion mechanism | Unit | Harness | Live | Entry id |
|---|---|---|---|---|---|---|---|---|---|
| scalar integer | `scalar` | plain | `42` | one dynamic or plain box | `planEntry` → `enterPlan` | yes | yes | yes | `scalar-plain` |
| scalar rational | `scalar` | fraction | `1/2` | one box, Fraction template | `planEntry` → `planFractionTemplate` | yes | no | yes | `scalar-fraction` |
| scalar rational, no template | `scalar` | fraction | `1/2` | one drawn box whose character set holds the slash | `planFractionBySlash` | yes | no | yes | `scalar-fraction-slash` |
| radical | `scalar` | radical | `sqrt(101)` | one box, Radical template | `planRun` | yes | no | yes | `scalar-radical` |
| symbolic with an exponent | `scalar` | exponent | `-x^13+2*x^12-3*x^11+5` | one box, Exponent template | `planRun` | yes | no | yes | `scalar-exponent` |
| factored product | `scalar` | group | `(x+3)*(x+4)` | one box, parentheses template | `planRun` | yes | no | yes | `scalar-group` |
| rational exponent | `scalar` | fraction+exponent+group | `y^(23/20)` | one box, Exponent over a bracketed rational | `planRun` | yes | no | yes | `scalar-fraction-exponent-group` |
| line's right side, rational coefficient | `scalar` | fraction+group | `(1/2)*x+8` | one full-keypad box the page prints `f(x) =` in front of, Fraction inside parentheses | `planEntry` → `planRun` → `planCommaList` → `planFractionTemplate` | yes | no | no | `scalar-fraction-group` |
| rationalized radical | `scalar` | fraction+radical | `sqrt(5)/5` | one box, Fraction over a Radical | `planEntry` → `planFractionTemplate` → `planRun` | yes | no | yes | `scalar-fraction-radical` |
| radical with an exponent | `scalar` | radical+exponent | `2*i*x^4*sqrt(2*x)` | one box, Radical inside a run of templates | `planRun` | yes | no | yes | `scalar-radical-exponent` |
| named phrase, typed | `scalar` | phrase | `trinomial` | one box accepting letters | `planEntry` → `enterPlan` | yes | no | no | `scalar-phrase` |
| ordered pair, integer components | `ordered-pair` | group+comma | `(3,-1)` | page draws ( [box] ), no parentheses template | `pageBracketedPair` → `planAnswerParts` | yes | no | yes | `ordered-pair-group-comma` |
| ordered pair, rational components | `ordered-pair` | fraction+group+comma | `(17/2,-1/2)` | one box, PBrace and Fraction | `planCommaList` → `planFractionTemplate` | yes | no | yes | `ordered-pair-fraction-group-comma` |
| multipart scalars | `parts` | plain | `-3` | several drawn boxes, one per value | `planAnswerParts` → `enterOwnedFields` | yes | yes | yes | `parts-plain` |
| multipart rationals over radicals | `parts` | fraction+radical+group | `(-3+sqrt(17))/2` | one control per value, each planned on its own | `planAnswerParts` → `planFractionTemplate` → `planRun` | yes | no | yes | `parts-fraction-radical-group` |
| multipart rational roots | `parts` | fraction | `-4/3` | one comma-answer box offering the Fraction template | `commaAnswerPlan` → `planAnswerParts` → `planFractionTemplate` | yes | no | no | `parts-fraction` |
| multipart ordered pairs with integer components | `parts` | group+comma | `(1,-3)` | several full-keypad boxes, one per ordered pair | `multiEntryPlans` → `planEntry` → `planRun` → `planCommaList` | yes | no | no | `parts-group-comma` |
| multipart ordered pairs with rational components | `parts` | fraction+group+comma | `(0,-1/6)` | several full-keypad boxes, one per rational ordered pair | `multiEntryPlans` → `planEntry` → `planRun` → `planCommaList` → `planFractionTemplate` | yes | no | no | `parts-fraction-group-comma` |
| named alternative | `choice` | phrase | `Quadrant IV` | one radio group, N buttons | `answerFitsEditor` | yes | no | yes | `choice-phrase` |
| named alternative carrying a set notation | `choice` | group | `Infinite Solutions (ℝ)` | one radio group whose labels gloss themselves, `No Solution (∅)` | `answerFitsEditor` | yes | no | yes | `choice-notated` |
| parabola graph plan | `parabola_plan` | *plan* | `plan, no value` | vertex and two symmetric controls | `graphOperation` | yes | no | yes | `plan-parabola` |
| literal points graph plan | `point_plot_plan` | *plan* | `plan, no value` | one draggable control per point | `graphOperation` | yes | no | yes | `plan-point-plot` |
| quadratic regression plan | `quadratic_regression` | *plan* | `plan, no value` | coefficients checked, then read | `graphOperation` | yes | no | yes | `plan-quadratic-regression` |
| factored form with an exponent | `scalar` | exponent+group | `-5*x*(2*y^2+3*y-5)` | one box, Exponent inside a parentheses template | `planRun` | yes | no | yes | `scalar-exponent-group` |
| multipart complex rationals | `parts` | fraction+group | `(-4-6*i)/7` | one control per value, each a fraction over a bracketed sum | `planAnswerParts` → `planFractionTemplate` → `planRun` | yes | no | yes | `parts-fraction-group` |
| an exact amount in cents | `scalar` | decimal | `79.00` | one plain box whose character rule admits the decimal point | `planEntry` → `enterPlan` | yes | no | no | `scalar-decimal-price` |
| line in slope-intercept form, whole equation | `relation` | plain | `y=-2*x+5` | one box publishing `=`, with no subject printed in front | `surfaceStatesSubject` → `planEntry` → `enterPlan` | yes | no | no | `relation-plain` |
| interval, one end open and one closed | `scalar` | group+comma+interval | `(-8,7]` | one box publishing `∞` and `∅`, a bracket template for each pairing of ends | `planEntry` → `planRun` → `planCommaList` → `enterPlan` | yes | no | yes | `scalar-interval` |
| interval with a decimal end and an infinite one | `scalar` | group+comma+decimal+interval | `[-2.5,∞)` | the same box; `∞` and the decimal point are characters it publishes | `planEntry` → `planRun` → `planCommaList` → `enterPlan` | yes | no | no | `scalar-interval-decimal` |
| the empty set | `scalar` | interval | `∅` | the same box, whose character set holds `∅` | `planEntry` → `planRun` → `enterPlan` | yes | no | no | `scalar-interval-empty` |
| a solution set graphed on a number line | `scalar` | group+comma+interval | `(-6,7]` | a QNumberLine with interval buttons and labelled ticks, no answer box | `number_line_plan` → `graphOperation` → `numberLine` | yes | no | yes | `scalar-interval-number-line` |
| union of intervals, typed | `scalar` | group+comma+interval | `(-∞,1]∪[4,∞)` | one box publishing `∪`, a bracket template for each end pairing | `planEntry` → `planRun` → `planCommaList` → `enterPlan` | yes | no | no | `scalar-interval-union-typed` |
| union of intervals, graphed | `scalar` | group+comma+interval | `(-∞,1)∪(4,∞)` | a QNumberLine taking up to its `maxplots` intervals | `number_line_plan` → `graphOperation` → `numberLine` | yes | no | no | `scalar-interval-union-number-line` |
| interval with a rational end, graphed | `scalar` | fraction+group+comma+interval | `(-∞,-7/2)` | a QNumberLine whose own grid has a tick at the end, here a subtick at every half | `number_line_plan` → `graphOperation` → `numberLine` | yes | no | no | `scalar-interval-fraction-number-line` |
| interval open at two finite ends | `scalar` | group+comma | `(1,4)` | the same box, `PBrace` around both ends; with no `∞` and no square bracket the value reads as a pair does | `planEntry` → `planRun` → `planCommaList` → `enterPlan` | yes | no | no | `scalar-interval-open` |
| interval open at two decimal ends | `scalar` | group+comma+decimal | `(-0.5,1.5)` | the same box; the decimal point is a character it publishes | `planEntry` → `planRun` → `planCommaList` → `enterPlan` | yes | no | no | `scalar-interval-open-decimal` |
<!-- /generated:supported -->

**Unit** means a QuickJS or Python test drives the real module. **Harness**
means `scripts/run_extension_harness.py` exercises it in a real Firefox -- it
has no native host, so it proves injection and reading, never a solve. **Live**
means it has been observed working in the owner's own session, through the
retained ledger or the observatory.

## Unsupported compositions

Named rather than discovered. Each is refused cleanly today, by the code its row
names; none is silently mis-entered.

<!-- generated:unsupported -->
| Composition | Example | Why | What happens now | Entry id |
|---|---|---|---|---|
| a decimal where the box has no decimal point | `8.5` | A box with no decimal point is asking for the exact form, and rewriting a value to fit a box is how a wrong answer gets typed in confidently. | Refused as `answer-has-rejected-characters` | `scalar-decimal` |
| union of intervals | `(-∞,-3)∪(3,∞)` | Hawkes' own editor refuses a `∪` key in a box whose characters do not include it, and this box publishes `∞` and `∅` only. The planner refuses the same character before a key is pressed; the same union goes in wherever the box publishes `∪` (`scalar-interval-union-typed`). | Refused as `answer-has-rejected-characters` | `scalar-interval-union` |
| interval whose end has no template | `[-2,5)` | A closed end is drawn by `SBrace`, `PSBrace` or `SPBrace` and by nothing else. A question that offers none of them is not asking for one, and an open bracket in its place is a different interval. | Refused as `template-refused-by-question` | `scalar-interval-unoffered-bracket` |
| a choice typed into a field | `Quadrant IV` | Selecting stays the reader's action, always. | Refused as `editor-option-answer` | `choice-typed` |
| interval with a rational end, typed | `(-∞,-7/2)` | Facet writes a rational end as a fraction unless the question asks for decimals, and this box offers no Fraction template and publishes no slash, so the planner refuses the `/` before a key is pressed. It is not rewritten as `-3.5` to fit: which spelling this box takes for a rational end has not been observed, and rewriting a value to fit a box is how a wrong answer gets typed in confidently. | Refused as `answer-has-rejected-characters` | `scalar-interval-fraction` |
| interval open at two rational ends, typed | `(1/2,7/2)` | `scalar-interval-fraction`'s refusal, for its reason: this box takes neither a `/` nor a Fraction template, and a rational end is not rewritten as a decimal to fit. Declared on its own because, with no infinite end, it reads as a pair of rationals rather than as interval notation. | Refused as `answer-has-rejected-characters` | `scalar-interval-open-fraction` |
| named function's whole equation | `f(x)=-5*x-3` | Every observed page that names a function prints `f(x) =` beside its box, so the right side alone is what it takes and this is never asked for. The one box that does take an equation publishes `xy=+-` and digits: a name and its brackets are both outside it. | Refused as `answer-has-rejected-characters` | `relation-group` |
| equation with a rational coefficient, whole | `y=(1/2)*x+8` | A rational coefficient is parenthesised so that `1/2x` cannot be read as `1/(2x)`, and parentheses can only come from a template. The observed equation box offers Fraction and no other, so this is refused by name rather than entered as a different number. | Refused as `template-refused-by-question` | `relation-fraction-group` |
<!-- /generated:unsupported -->

## Adding a family

1. Emit the answer with the right `form`. Add a row to
   `facet-runtime/tests/test_answer_forms.py`.
2. Add an entry to **`docs/answer-capabilities.json`**: the composition, the
   page topology, the mechanism, and a `probe` -- a real question that makes the
   solver emit it. Then
   `python3 scripts/render_answer_capabilities.py --write`.
3. If there is no mechanism, give the entry `"status": "unsupported"` and the
   `refusal` code it is actually refused by. That is a finished state. What is
   not a finished state is discovering it live.
4. `tests/test_answer_compatibility.py` will run it: the probe against the real
   solver, the example against the shipped planner, the runtime's own exact
   emitter tests, and the whole lesson corpus against your new declaration.

## See also

- [The Ethnos-Facet boundary](FACET_BRIDGE.md) — the protocol these answers cross
- [Retained failure ledger](FAILURE_LEDGER.md) — where an uninsertable answer shows up
- [Hawkes editor findings](HAWKES_EDITOR_FINDINGS.md) — what the page publishes
