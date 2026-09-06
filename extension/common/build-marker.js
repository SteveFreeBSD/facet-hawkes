"use strict";

/**
 * A digest of the code Firefox actually loaded, computed by that code.
 *
 * The add-on already logs its manifest version, and that version is not the
 * question. A temporary add-on keeps the same version across every edit, and
 * `about:debugging`'s Reload re-reads whichever directory was first selected —
 * so the build under test and the build being edited can be different files
 * with identical version numbers. Hours have gone into diagnosing a bug that
 * was already fixed in a tree Firefox was not running.
 *
 * Nothing outside the browser can answer this. Hashing the source tree says
 * what the *next* load would run; only the running code can say what this one
 * did. It says it by reading its own source back — `Function.prototype
 * .toString()` returns the text Firefox parsed — and folding that into one
 * short marker.
 *
 * Reading the package back over its own extension URLs would be the obvious
 * way and is not available: `scripts/build_extension.py` forbids both the
 * request and the URL helper outright, because this add-on promises to make no
 * request and to leave no profile-unique URL anywhere a page could see one.
 * Neither promise is worth weakening for a diagnostic. Source text costs
 * nothing and crosses no boundary.
 *
 * The algorithm is fixed here and mirrored in
 * `scripts/observe_live_hawkes.py`, which evaluates the same modules off disk
 * and folds them the same way — so an observer can say "running the working
 * tree" or "running something else" instead of guessing.
 *
 *   symbol  = "<module>#<export>" or "<name>"
 *   line    = "<symbol> " + sha256(source text)
 *   marker  = sha256(sorted lines joined by "\n", trailing "\n")[:12]
 *
 * What it covers is the event page's own module graph and the functions named
 * to {@link collectSources}. The panel, the settings page and the injected
 * content scripts load in other contexts and are not in it; the observer
 * covers those with the working tree's git state and file times, and says so
 * rather than implying more than this marker proves.
 */

/** Length of the reported marker. Twelve hex characters; a name, not a proof. */
export const MARKER_LENGTH = 12;

/** Longest source text hashed for one symbol. Beyond this, code is pathological. */
const MAX_SOURCE = 200000;

function hex(buffer) {
  return [...new Uint8Array(buffer)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

async function sha256(text) {
  return hex(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)));
}

/**
 * The source text of one exported value.
 *
 * A function stringifies to its own source, which is the whole point. A
 * constant does not — every frozen object is `[object Object]` — so data
 * exports are serialized instead, and a settings schema or a character set
 * therefore changes the marker as readily as a function body does.
 */
function sourceOf(value) {
  if (typeof value === "function") {
    return String(value).slice(0, MAX_SOURCE);
  }
  try {
    return JSON.stringify(value ?? null).slice(0, MAX_SOURCE);
  } catch {
    return "unserializable";
  }
}

/**
 * Flatten modules and functions into named source texts.
 *
 * A module namespace is expanded into one entry per export, so adding an
 * export changes the marker and nothing has to be listed by hand. A bare
 * function is one entry under its own name, which is how the event page
 * contributes its own code: it exports nothing, being the entry module.
 *
 * @param {Record<string, object|Function>} parts
 * @returns {[string, string][]} sorted `[symbol, source]` pairs
 */
export function collectSources(parts) {
  const entries = [];
  for (const [name, part] of Object.entries(parts)) {
    if (typeof part === "function") {
      entries.push([name, sourceOf(part)]);
      continue;
    }
    if (!part || typeof part !== "object") {
      continue;
    }
    for (const key of Object.keys(part).sort()) {
      entries.push([`${name}#${key}`, sourceOf(part[key])]);
    }
  }
  return entries.sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0));
}

/**
 * Fold named source texts into one marker.
 *
 * @param {[string, string][]} entries from {@link collectSources}
 * @returns {Promise<{marker: string, symbols: number, chars: number}>}
 */
export async function foldSources(entries) {
  const lines = [];
  let chars = 0;
  for (const [symbol, source] of entries) {
    chars += source.length;
    lines.push(`${symbol} ${await sha256(source)}`);
  }
  lines.sort();
  return {
    marker: (await sha256(`${lines.join("\n")}\n`)).slice(0, MARKER_LENGTH),
    symbols: entries.length,
    chars,
  };
}
