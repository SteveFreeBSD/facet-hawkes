"use strict";

// Development-only live-proof bridge. It asks the background to close this
// internal tab, then invoke Facet's existing Solve and Insert operations. The
// lesson tab therefore becomes active again without navigation or a tab-
// activation capability, and the background owns all pinning and readback.
const TARGET_ADDON_ID = "ethnos-hawkes@local";
const STATE_KEY = "facetDevelopmentReviewedInsertion";
const NONCE = new URLSearchParams(window.location.search).get("nonce") ?? "";
const status = document.getElementById("status");
let finished = false;

async function closeThisTab() {
  const tab = await browser.tabs.getCurrent();
  if (Number.isInteger(tab?.id)) {
    await browser.tabs.remove(tab.id);
  }
}

async function finish(phase, fields) {
  if (finished) return;
  finished = true;
  await browser.storage.local.set({
    [STATE_KEY]: { addonId: TARGET_ADDON_ID, nonce: NONCE, phase, ...fields },
  });
  status.textContent = "Insertion proof complete; closing…";
  setTimeout(async () => {
    await browser.storage.local.remove(STATE_KEY);
    await closeThisTab();
  }, 8000);
}

async function insertReviewed() {
  if (browser.runtime.id !== TARGET_ADDON_ID || !/^[a-f0-9]{32}$/.test(NONCE)) {
    await finish("refused", { reason: "extension identity or request is invalid" });
    return;
  }
  const candidates = (await browser.tabs.query({ url: "*://learn.hawkeslearning.com/*" }))
    .filter((tab) => /\/Portal\/Lesson\//i.test(String(tab.url || "")));
  if (
    candidates.length !== 1
    || !Number.isInteger(candidates[0].id)
    || !Number.isInteger(candidates[0].windowId)
  ) {
    await finish("refused", {
      reason: `expected one Hawkes lesson tab, found ${candidates.length}`,
    });
    return;
  }

  const target = candidates[0];
  const helper = await browser.tabs.getCurrent();
  if (!Number.isInteger(helper?.id)) {
    await finish("refused", { reason: "the internal helper tab could not be proved" });
    return;
  }
  const port = browser.runtime.connect({ name: "ethnos:panel" });
  await browser.storage.local.set({
    [STATE_KEY]: {
      addonId: TARGET_ADDON_ID,
      nonce: NONCE,
      phase: "requested",
    },
  });
  port.postMessage({ type: "ethnos:hello", windowId: target.windowId });
  port.postMessage({
    type: "ethnos:development-insert-pair",
    windowId: target.windowId,
    tabId: helper.id,
    targetTabId: target.id,
    nonce: NONCE,
  });
}

insertReviewed().catch((error) => finish("refused", {
  reason: String(error?.message ?? error).slice(0, 300),
}));
