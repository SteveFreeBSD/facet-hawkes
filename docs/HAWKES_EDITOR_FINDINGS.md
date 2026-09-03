# Hawkes answer editor: observed behaviour

Recorded from a live `learn.hawkeslearning.com` practice lesson on 2026-09-02,
driven through `scripts/live_browser.py`. Everything here was observed, not
inferred from documentation. Lesson 1.2, "Properties of Exponents and
Radicals".

## The answer entry is structured, not a text box

A question starts with a single base input:

```
INPUT#QBase1_input.qbaseCSS        maxlength=500, type=text, in the top frame
```

Pressing a keypad template replaces it with named part inputs. `Fraction`
produces:

```
INPUT#txtAns1_num.boxStyle.boxStyleFont1.nocontextmenu    numerator, focused
INPUT#txtAns1_den.boxStyle.boxStyleFont1.nocontextmenu    denominator
```

So the entry model is a tree of small inputs with predictable names, which is
what an answer-AST-to-editor adapter needs. It is not a field you can type a
complete expression into.

The lesson page has one iframe, and it is a feedback dialog
(`#textAreaQuestion`, `#feedBackTextarea`) — not the answer. The answer inputs
live in the top frame.

## Characters are whitelisted per question, and rejection is loud

Probed against `9/√(5x)`, whose only variable is `x`:

| Sent | Kept | Note |
|---|---|---|
| `x` | `x` | the question's own variable |
| `y`, `z`, `a` | *(empty)* | any other letter is dropped |
| `X` | `x` | case is normalised |
| `5x` | `5x` | |
| `5y` | `5` | the letter alone is dropped |
| `9x5` | `9x5` | |
| `+` | `+` | |
| `(`, `)` | *(empty)* | grouping comes from the keypad |
| `9/5` | `95` | the slash is dropped |
| `-3.5` | `-35` | the decimal point is dropped |
| `sqrt` | *(empty)* | |

Two consequences:

1. **The editor does react to programmatic input.** Its sanitiser ran
   *synchronously inside the add-on's `input` event dispatch* — the value was
   already filtered by the time the insertion code returned. So the add-on's
   existing technique (assign through the prototype setter, then dispatch
   `beforeinput` and `input` as a real `InputEvent`) is the right one. No
   `change` event and no synthetic keystrokes are needed.
2. **A disallowed character raises a blocking modal**, not a silent strip:
   `#PracticecustomMessageBox` — *"The character you entered is not required in
   the answer. Please try again!"* — with `#PracticecustomMessageBoxClose` to
   dismiss. It holds focus until dismissed, so any later `focus()` call fails
   silently. Inserting a wrong-form answer is therefore visible to the user and
   leaves the page stuck.

This is why an answer containing `(`, `)`, `/`, or `.` must not be inserted at
all. The add-on shows those for manual entry instead.

## The keypad

Collapsed behind `#btnShowKeypad`, inside `#collapse-keypad` (a Bootstrap
collapse). The template buttons are `<a href="#">` elements with **direct
jQuery `click` handlers** (`jQuery._data(el, "events")` → `["click"]`) and no
inline `onclick`. Their ids map almost one-to-one onto the answer AST:

| Keypad id | AST node |
|---|---|
| `Exponent` | `power` |
| `Subscript` | — |
| `Fraction` | `fraction` |
| `Radical` | `square_root` |
| `IndexedRadical` | `indexed_root` |
| `PBrace`, `PSBrace`, `SPBrace`, `SBrace`, `CBrace`, `ABrace` | `parenthesized` and bracket variants |
| `symPlus` | `sum` |
| `symMinus` | `negative` |
| `symPlusOrMinus` | `plus_minus` |
| `GrInteger`, `symMod`, `DashedChar` | greatest integer, modulus, dashed placeholder |

Hawkes also binds `click`, `focusin`, `focusout`, `keydown` and `mouseup`
handlers at document level, which is presumably how it tracks which box is
active when a keypad button takes focus.

### Driving the keypad: solved

Reading the handler chain settled it. The keypad anchors do:

```js
function () { ListenKeyPadButtonClick(this.id, () => $("#" + this.id).focus()); }
```

`ListenKeyPadButtonClick` gates on `quant_wp_UI.focusedElementIndex`, and for a
dynamic box dispatches to `control.keyPadButtonClick(name, cb)`, which is
`objMe.addElement(name, true, cb)`:

```js
} else if (ObjType == 'Exponent') {
    TempObj = objMe.CurrentBase;
    if (TempObj.qualifyLoadExponent()) {
        TempObj.loadExponent(EventFromKeyPad);
    } else {
        ShowInvalidInputForm = true;   // the "character not required" dialog
        TempObj.setFocus();
    }
}
```

Two things follow, and both had been masked:

1. **A template needs a base to attach to.** Every earlier attempt pressed
   Exponent on an *empty* box, so `qualifyLoadExponent()` returned false and
   the branch raised the dialog. The dialog is not about a rejected character
   at all — it is the editor's generic refusal.
2. **That dialog is modal and holds focus**, so once it appeared every later
   `focus()` silently failed and subsequent probes were measuring a page that
   could not respond.

The working sequence, verified live on `⁵√(y⁵x³⁰z²⁵)` = `x⁶yz⁵`:

| Step | Call | Result |
|---|---|---|
| type the base | set `.value`, dispatch `InputEvent("input")` | `QBase3_input="x"` |
| press template | `control.keyPadButtonClick("Exponent", cb)` | `QBase4_input` appears, **focused**; `QBase6_input` added as the continuation base |
| type the exponent | same input technique on `QBase4_input` | `QBase4_input="6"` |
| continue | type into `QBase6_input` | `QBase6_input="yz"` |
| press template again | `keyPadButtonClick("Exponent", cb)` | `QBase7_input` appears, focused |
| type | `QBase7_input="5"` | renders `x⁶yz⁵` |

No dialog at any step. So structured entry is fully drivable, provided each
template is pressed only when the box it attaches to is non-empty.

`addElement` also names every template it accepts: `Clear`, `BS`, `Fraction`,
`Radical`, `IndexedRadical`, `Exponent`, `Subscript`, the bracket family
(`PBrace`, `SBrace`, `PSBrace`, `SPBrace`, `CBrace`, `Mod`, `GrInteger`,
`DblBar`, `ABrace`, `Integral`, `Sigma`), and the function family (`ln`, `log`,
`sin`…`acot`).

**Plain answer boxes are different.** `AnswerBoxKeyPadClick` builds structure by
editing the value directly — `case 'Fraction': focusedElement.value = prevText
+ '/' + postText` — so in a plain box a fraction really is a typed `/`, subject
to that box's `validString`.

### Nesting, and finding the slots

Templates nest in both directions, and all three shapes below were entered
programmatically end to end with no dialog:

| Answer | Question | Shape |
|---|---|---|
| `x⁶yz⁵` | `⁵√(y⁵x³⁰z²⁵)` | exponent after a base, twice |
| `1/(12x⁷y)` | `√(y³/(144x¹⁴y⁵))` | fraction, with an exponent inside the denominator |
| `a^(1/2)` | `a^(1/6)·a^(1/3)` | fraction inside an exponent |

`Fraction` **does** load on an empty box; only `Exponent` needs something to
attach to. After loading a fraction the editor focuses the **numerator**, so a
plan types the numerator first and then moves to the denominator.

Slot boxes are not named by role — they are all `input.qbaseCSS` with
sequential `QBase<n>_input` ids, and the numbering is not contiguous. So slots
are found by **diffing the visible box list across the template press**, not by
predicting ids. For `1/(12x⁷y)`:

```text
before Fraction:  QBase10
after  Fraction:  QBase10, QBase12*, QBase14, QBase11     * = focused
                            numerator  denominator  continuation-after
after  Exponent:  ... QBase17*, QBase19 ...
                       exponent  continuation-inside-denominator
```

The newly focused box is the first slot to fill. The remaining new boxes are
the other slots, in document order.

### Executing a plan

The slot-diffing above is enough to run a whole plan without knowing any box id
in advance. Verified end to end on `y^(3/2)`, from a plan the shipped
`editor-plan.js` produced:

```text
cursor  = the first visible input.qbaseCSS
type    -> write into cursor
template-> record the visible box ids, press, then diff:
             the newly focused box becomes the cursor
             the other new boxes become pending slots, in document order
slot    -> take the next pending slot as the cursor
```

```text
type "y"          QBase31="y"
press Exponent    focus QBase32, pending [QBase34]
press Fraction    focus QBase36, pending [QBase38, QBase35]
type "3"          QBase36="3"          (numerator, auto-focused)
slot denominator  cursor QBase38
type "2"          QBase38="2"          renders y^(3/2)
```

Two levels of nesting, no dialog, and no id predicted. Note the ids are neither
contiguous nor ordered by role — `QBase38` is the denominator while `QBase35`
is the continuation after the fraction — which is exactly why the focused box
must be taken from the DOM rather than inferred.

Per-slot character sets are published separately and differ from the base:
`qdyFrac_AllowedNumeChar`, `qdyFrac_AllowedDenoChar`,
`qdyRoot_AllowedRadicandChar`, `qdyRoot_AllowedIndexChar`,
`qdyExpo_AllowedChar`. On question 10 the base allowed `0123456789yxz-` while
the numerator allowed `0123456789yx-` and the denominator `0123456789yxz`.

### Previously unresolved (superseded)

With `#txtAns1_num` focused, **none** of these made a radical appear inside the
numerator:

- `element.click()`
- a full synthetic sequence: `pointerdown`, `mousedown`, `pointerup`,
  `mouseup`, `click` at the button's real coordinates
- a **trusted** click via Marionette's `WebDriver:ElementClick`

The trusted click failing is the important part: it rules out an
`isTrusted` check, which would have been a hard limit on any extension. So the
obstacle is something else — the anchor taking focus before the handler reads
the active box, the template not being applicable at that position, or the
question's own answer template constraining what the keypad offers.

**This result is inconclusive.** The lesson re-rendered to a different question
during the probe (`#QBase1_input` and the `.DynamicBox` container disappeared,
`#txtAns1_den` went offscreen, and an option checkbox appeared), so the final
attempts ran against a page whose shape had changed underneath them. Re-run on
a freshly loaded question of a known type before drawing a conclusion.

## What this means for insertion

- Filling a box works, and is verified.
- Building structure works, and is verified for exponents, fractions, and both
  nestings of the two.
- `extension/common/editor-plan.js` turns an answer into the ordered plan of
  typing and template presses, refusing what it cannot build rather than
  entering it partially. `tests/test_hawkes_plan.py` pins the two plans that
  were verified live.
- The planner now covers square and indexed radicals, a fraction inside an
  exponent, parenthesized groups, and absolute-value bars when the question's
  published template set permits them. These paths are pinned in
  `tests/test_hawkes_plan.py`; rational exponents and retained radicals have
  also been exercised in the live lesson.
- **Wired.** `common/page-actions.js` performs a plan in the page's own world.
  It keeps a stack of template frames so a slot move returns to the structure
  it belongs to, and predicts no box ids. Verified on the live lesson building
  `√(30yz)/(5z)` from `√(6y/(5z))`.
- **Still not planned:** nested fractions. They are declined before the page is
  touched rather than partially entered.

## Footprint consequence

Taken, deliberately, in 0.16.0.

The read-only probe already gave up strict undetectability while it ran. The
executor goes further: it calls the page's own editor methods, so the editor's
internal state changes through its own code paths rather than through
synthesized events. That is *more* faithful to a real user — the resulting DOM
and model are exactly what a human click produces — but the add-on is now
unambiguously operating inside the page's world.

It was necessary rather than convenient. Structure cannot be typed: Hawkes
refuses `/` and `(` outright with a blocking dialog, and builds structure only
through `keyPadButtonClick`. Neither a synthesized event sequence nor a
**trusted** click reaches it, so there is no route that stays outside the
page's world.

The capability is bounded and the build enforces the bounds: the writer may
type into answer boxes and press named templates, and may not evaluate code,
click page elements, navigate, make requests, or write markup. Submission
remains out of scope entirely — as does selecting a radio button, which is
answering rather than filling in a field.

## Reproducing

```console
$ python3 scripts/live_browser.py start        # throwaway profile, add-on installed
$ python3 scripts/live_browser.py go https://learn.hawkeslearning.com
$ python3 scripts/live_browser.py field        # every candidate answer input
$ python3 scripts/live_browser.py page         # the focused element's shape
$ python3 scripts/live_browser.py stop
```

The browser is a separate instance on a temporary profile; it never touches the
user's own Firefox, profile, or sessions. Probing writes to the answer field, so
use a practice question and expect to reload it afterwards.
