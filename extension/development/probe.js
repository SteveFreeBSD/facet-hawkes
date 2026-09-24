"use strict";

// Development-only, reached by scripts/probe_live_hawkes_contract.py.  It
// injects the same read-only descriptor used by normal solves and records its
// bounded return value.  It does not dispatch events or alter coursework.
const TARGET_ADDON_ID = "ethnos-hawkes@local";
const PROBE_STATE_KEY = "facetDevelopmentContractProbe";
const parameters = new URLSearchParams(window.location.search);
const NONCE = parameters.get("nonce") ?? "";
const status = document.getElementById("status");

async function closeThisTab() {
  const tab = await browser.tabs.getCurrent();
  if (Number.isInteger(tab?.id)) {
    await browser.tabs.remove(tab.id);
  }
}

async function finish(phase, fields) {
  await browser.storage.local.set({
    [PROBE_STATE_KEY]: {
      addonId: TARGET_ADDON_ID,
      nonce: NONCE,
      phase,
      ...fields,
    },
  });
  status.textContent = "Contract inspection complete; closing…";
  setTimeout(async () => {
    await browser.storage.local.remove(PROBE_STATE_KEY);
    await closeThisTab();
  }, 8000);
}

async function probe() {
  if (browser.runtime.id !== TARGET_ADDON_ID || !/^[a-f0-9]{32}$/.test(NONCE)) {
    status.textContent = "Probe refused: extension identity or request is invalid.";
    return;
  }
  const candidates = (await browser.tabs.query({ url: "*://learn.hawkeslearning.com/*" }))
    .filter((tab) => /\/Portal\/Lesson\//i.test(String(tab.url || "")));
  if (candidates.length !== 1 || !Number.isInteger(candidates[0].id)) {
    await finish("refused", {
      reason: `expected one Hawkes lesson tab, found ${candidates.length}`,
    });
    return;
  }
  const injected = await browser.scripting.executeScript({
    target: { tabId: candidates[0].id, frameIds: [0] },
    world: "MAIN",
    files: ["/development/probe-main.js"],
  });
  await finish("completed", {
    tabId: candidates[0].id,
    result: injected?.[0]?.result ?? null,
  });
}

probe().catch((error) => finish("refused", {
  reason: String(error?.message ?? error).slice(0, 300),
}));
