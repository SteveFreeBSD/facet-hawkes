"""A DOM small enough to read a Hawkes fixture with, and no larger.

`extension/content/hawkes-question.js` is a read-only DOM probe, so exercising
it needs a document. QuickJS has none, and the alternative -- hand-building an
object graph per test -- makes every test a statement about the graph somebody
wrote rather than about the page in `tests/fixtures/`.

So the fixture is parsed here, with the standard library, and the result is
given to QuickJS as a node tree with the handful of DOM methods that file
actually calls. Two things are honest to say about it:

*   **Structure is the fixture's.** Elements, attributes, nesting, text nodes
    and document order all come from the markup, not from this module.
*   **Layout is synthetic.** Nothing here renders, so rectangles are assigned:
    a table cell is placed by its row and column, and everything else by
    document order. That is enough for the two geometric questions the probe
    asks -- what is above the answer line, and are the blanks in reading order
    -- and it is not a claim about how Firefox would lay the page out.
    `scripts/run_extension_harness.py` answers that one, in a real browser.
"""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
QUESTION_PROBE = PROJECT_ROOT / "extension" / "content" / "hawkes-question.js"

#: Elements that close themselves.
VOID = frozenset(
    {"input", "br", "img", "meta", "link", "hr", "source", "col", "area", "base"}
)

#: Nominal grid, in the same units document order uses.
ROW_HEIGHT = 40
COLUMN_WIDTH = 120


class _Tree(HTMLParser):
    """Markup to nested dicts. Text nodes are kept; comments and doctype are not."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root: dict = {"tag": "#root", "attrs": {}, "children": []}
        self._stack = [self.root]

    def handle_starttag(self, tag, attrs):
        # A valueless attribute reads back as the empty string, which is what
        # `getAttribute` returns for one. Keeping `None` made `disabled` and
        # `readonly` indistinguishable from absent to any probe that compares
        # against null -- true of the reader, and of nothing in a browser.
        node = {
            "tag": tag,
            "attrs": {n: v if v is not None else "" for n, v in attrs},
            "children": [],
        }
        self._stack[-1]["children"].append(node)
        if tag not in VOID:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._stack[-1]["children"].append(
            {
                "tag": tag,
                "attrs": {n: v if v is not None else "" for n, v in attrs},
                "children": [],
            }
        )

    def handle_endtag(self, tag):
        for depth in range(len(self._stack) - 1, 0, -1):
            if self._stack[depth]["tag"] == tag:
                del self._stack[depth:]
                return

    def handle_data(self, data):
        if data:
            self._stack[-1]["children"].append({"text": data})


def _place(root: dict) -> None:
    """Give every element a rectangle.

    Document order drives the vertical position, so what the markup writes
    first sits above what it writes next -- which is the only ordering the
    probe's "above the answer line" rule depends on. Inside a table the cells
    are laid out as a grid from the table's own position, and anything inside a
    cell shares that cell's box, so an answer control in row three is at row
    three. Widths and heights are nominal and exist only so a node counts as
    visible.
    """
    order = [0]

    def walk(node: dict, inherited: dict | None) -> None:
        if "text" in node:
            return
        order[0] += 1
        if inherited is not None:
            node["rect"] = dict(inherited)
        elif node["tag"] == "table":
            node["rect"] = {
                "top": order[0] * 10,
                "left": 0,
                "width": 400,
                "height": 200,
            }
        else:
            node["rect"] = {"top": order[0] * 10, "left": 0, "width": 200, "height": 20}
        if "hidden" in node.get("attrs", {}):
            node["rect"] = {"top": 0, "left": 0, "width": 0, "height": 0}
        if node["tag"] == "table" and inherited is None:
            _place_table(node, walk)
            return
        for child in node["children"]:
            walk(child, inherited)

    def _place_table(table: dict, descend) -> None:
        base = table["rect"]["top"]
        for index, row in enumerate(_rows_of(table)):
            row["rect"] = {
                "top": base + ROW_HEIGHT * (index + 1),
                "left": 0,
                "width": 400,
                "height": ROW_HEIGHT,
            }
            for column, cell in enumerate(
                [one for one in row["children"] if one.get("tag") in {"td", "th"}]
            ):
                cell["rect"] = {
                    "top": row["rect"]["top"],
                    "left": column * COLUMN_WIDTH,
                    "width": COLUMN_WIDTH,
                    "height": ROW_HEIGHT,
                }
                for child in cell["children"]:
                    descend(child, cell["rect"])
        # Structural wrappers keep the table's own box.
        for node in _between(table):
            node.setdefault("rect", dict(table["rect"]))

    _link(root, None)
    walk(root, None)


def _between(table: dict) -> list[dict]:
    """`thead`, `tbody`, `tr` and anything else between a table and its cells."""
    found: list[dict] = []

    def walk(node: dict) -> None:
        for child in node.get("children", []):
            if "text" in child or child.get("rect") is not None:
                continue
            found.append(child)
            walk(child)

    walk(table)
    return found


def _link(node: dict, parent: dict | None) -> None:
    node["parent"] = parent
    for child in node.get("children", []):
        _link(child, node)


def _rows_of(table: dict) -> list[dict]:
    found: list[dict] = []

    def walk(node: dict) -> None:
        for child in node.get("children", []):
            if "text" in child:
                continue
            if child["tag"] == "tr":
                found.append(child)
            elif child["tag"] != "table":
                walk(child)

    walk(table)
    return found


def _strip(node: dict) -> dict:
    """The tree without the parent links, so it can be serialized."""
    if "text" in node:
        return {"text": node["text"]}
    return {
        "tag": node["tag"],
        "attrs": node["attrs"],
        "rect": node["rect"],
        "children": [_strip(child) for child in node["children"]],
    }


SHIM = r"""
// --- selectors -------------------------------------------------------------
// Only the forms `hawkes-question.js` uses: a tag name, `.class`, `#id`, and
// `[attr]`, `[attr="v"]`, `[attr^="v"]`, `[attr$="v"]`, joined into compounds
// and separated by commas.
const SIMPLE = /^([a-zA-Z][-\w]*|\*)?((?:[.#][-\w]+|\[[^\]]+\])*)$/;
const PIECE = /[.#][-\w]+|\[[^\]]+\]/g;
const ATTR = /^\[([-\w]+)(?:([~^$|*]?=)"?([^"\]]*)"?)?\]$/;

function matchesOne(node, selector) {
  const whole = SIMPLE.exec(selector.trim());
  if (!whole) return false;
  const [, tag, rest] = whole;
  if (tag && tag !== "*" && node.tagName.toLowerCase() !== tag.toLowerCase()) {
    return false;
  }
  for (const piece of rest.match(PIECE) ?? []) {
    if (piece[0] === ".") {
      if (!node.classList.includes(piece.slice(1))) return false;
    } else if (piece[0] === "#") {
      if (node.id !== piece.slice(1)) return false;
    } else {
      const found = ATTR.exec(piece);
      if (!found) return false;
      const [, name, operator, value] = found;
      const actual = node.attributes[name];
      if (actual === undefined) return false;
      if (!operator) continue;
      if (operator === "=" && actual !== value) return false;
      if (operator === "^=" && !actual.startsWith(value)) return false;
      if (operator === "$=" && !actual.endsWith(value)) return false;
    }
  }
  return true;
}

function matchesAny(node, selector) {
  return String(selector).split(",").some((one) => matchesOne(node, one));
}

// --- nodes -----------------------------------------------------------------
class DomNode {
  constructor(raw, parent) {
    this.nodeType = raw.text === undefined ? 1 : 3;
    this.parentElement = parent;
    if (this.nodeType === 3) {
      this.data = raw.text;
      this.childNodes = [];
      return;
    }
    this.tagName = raw.tag.toUpperCase();
    this.attributes = raw.attrs;
    this.id = raw.attrs.id ?? "";
    this.classList = (raw.attrs.class ?? "").split(/\s+/).filter(Boolean);
    this.rect = raw.rect;
    this.childNodes = raw.children.map((child) => new DomNode(child, this));
  }
  get textContent() {
    return this.nodeType === 3
      ? this.data
      : this.childNodes.map((child) => child.textContent).join("");
  }
  get children() {
    return this.childNodes.filter((child) => child.nodeType === 1);
  }
  getBoundingClientRect() {
    const r = this.rect ?? {top: 0, left: 0, width: 0, height: 0};
    return {
      top: r.top, left: r.left, width: r.width, height: r.height,
      right: r.left + r.width, bottom: r.top + r.height,
    };
  }
  matches(selector) {
    return this.nodeType === 1 && matchesAny(this, selector);
  }
  closest(selector) {
    for (let at = this; at; at = at.parentElement) {
      if (at.nodeType === 1 && matchesAny(at, selector)) return at;
    }
    return null;
  }
  descendants() {
    const found = [];
    const walk = (node) => {
      for (const child of node.childNodes) {
        if (child.nodeType === 1) { found.push(child); walk(child); }
      }
    };
    walk(this);
    return found;
  }
  querySelectorAll(selector) {
    return this.descendants().filter((node) => matchesAny(node, selector));
  }
  querySelector(selector) {
    return this.querySelectorAll(selector)[0] ?? null;
  }
  contains(other) {
    for (let at = other; at; at = at.parentElement) if (at === this) return true;
    return false;
  }
  // Tables. `rows` is every `tr` under a table or one of its sections, in
  // document order, which is what the DOM reports for both; `cells` is a row's
  // own cells.
  get rows() {
    return ["TABLE", "THEAD", "TBODY", "TFOOT"].includes(this.tagName)
      ? this.descendants().filter((node) => node.tagName === "TR")
      : [];
  }
  get tHead() {
    return this.descendants().find((node) => node.tagName === "THEAD") ?? null;
  }
  get cells() {
    return this.children.filter(
      (node) => node.tagName === "TD" || node.tagName === "TH"
    );
  }
}

globalThis.NodeFilter = {SHOW_TEXT: 4};

globalThis.XMLSerializer = function XMLSerializer() {
  const write = (node) => {
    if (node.nodeType === 3) return node.data;
    const name = node.tagName.toLowerCase();
    const attributes = Object.entries(node.attributes)
      .map(([key, value]) => ` ${key}="${value}"`)
      .join("");
    return `<${name}${attributes}>${node.childNodes.map(write).join("")}</${name}>`;
  };
  this.serializeToString = write;
};

globalThis.buildDocument = (raw) => {
  const root = new DomNode(raw, null);
  globalThis.document = {
    querySelectorAll: (selector) => root.querySelectorAll(selector),
    querySelector: (selector) => root.querySelector(selector),
    getElementById: (id) => root.descendants().find((node) => node.id === id) ?? null,
    createTreeWalker(node) {
      const texts = [];
      const walk = (at) => {
        for (const child of at.childNodes) {
          if (child.nodeType === 3) texts.push(child); else walk(child);
        }
      };
      walk(node);
      let at = -1;
      return {nextNode: () => (++at < texts.length ? texts[at] : null)};
    },
  };
  return root;
};
"""


def read_question(markup: str) -> dict:
    """Run the page probe over this markup and return what it read."""
    quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")
    tree = _Tree()
    tree.feed(markup)
    _place(tree.root)
    context = quickjs.Context()
    context.eval(SHIM)
    context.eval(f"buildDocument({json.dumps(_strip(tree.root))});")
    source = QUESTION_PROBE.read_text(encoding="utf-8")
    return json.loads(context.eval(source).json())


def read_fixture(name: str) -> dict:
    return read_question(
        (PROJECT_ROOT / "tests" / "fixtures" / name).read_text(encoding="utf-8")
    )
