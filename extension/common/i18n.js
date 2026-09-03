"use strict";

/**
 * Minimal declarative localisation for extension pages.
 *
 * Elements opt in with `data-i18n="messageName"` for text content and
 * `data-i18n-attr="attribute:messageName"` for attributes such as `title` or
 * `placeholder`. Nothing is ever assigned as HTML.
 */

/**
 * Look up a message, returning the key itself if the catalogue lacks it so a
 * missing string is visible during review rather than silently blank.
 *
 * @param {string} name
 * @param {string[]} [substitutions] values for the message's `$1`-style slots
 * @returns {string}
 */
export function message(name, substitutions) {
  return browser.i18n.getMessage(name, substitutions) || name;
}

/**
 * Replace the text of every `data-i18n` element inside `root`.
 *
 * @param {ParentNode} [root=document]
 */
export function localizeDocument(root = document) {
  for (const element of root.querySelectorAll("[data-i18n]")) {
    element.textContent = message(element.dataset.i18n);
  }
  for (const element of root.querySelectorAll("[data-i18n-attr]")) {
    for (const pair of element.dataset.i18nAttr.split(",")) {
      const [attribute, name] = pair.split(":").map((part) => part.trim());
      if (attribute && name) {
        element.setAttribute(attribute, message(name));
      }
    }
  }
}
