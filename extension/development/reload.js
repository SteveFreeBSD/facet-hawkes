"use strict";

// Development-only, reached through Firefox's profile-scoped D-Bus remote
// service by scripts/reload_live_hawkes.py.  It can reload only the extension
// whose origin loaded it, and verifies the permanent ID before doing so.
const TARGET_ADDON_ID = "ethnos-hawkes@local";
const NONCE_KEY = "facet-hawkes-development-reload";
const RELOAD_STATE_KEY = "facetDevelopmentReload";
const NONCE = new URLSearchParams(window.location.search).get("nonce") ?? "";
const status = document.getElementById("status");

async function closeThisTab() {
  const tab = await browser.tabs.getCurrent();
  if (Number.isInteger(tab?.id)) {
    await browser.tabs.remove(tab.id);
  }
}

async function reload() {
  if (browser.runtime.id !== TARGET_ADDON_ID || !/^[a-f0-9]{32}$/.test(NONCE)) {
    status.textContent = "Reload refused: extension identity or request is invalid.";
    return;
  }

  // Firefox may restore an extension tab when its extension is reloaded.  The
  // nonce makes that second load a cleanup pass instead of a reload loop.
  if (window.localStorage.getItem(NONCE_KEY) === NONCE) {
    window.localStorage.removeItem(NONCE_KEY);
    await closeThisTab();
    return;
  }

  window.localStorage.setItem(NONCE_KEY, NONCE);
  await browser.storage.local.set({
    [RELOAD_STATE_KEY]: {
      addonId: TARGET_ADDON_ID,
      nonce: NONCE,
      phase: "requested",
      requestedAt: Date.now(),
    },
  });
  status.textContent = "Reloading the temporary Facet Hawkes add-on…";
  browser.runtime.reload();
}

reload().catch((error) => {
  status.textContent = `Reload refused: ${String(error?.message ?? error).slice(0, 160)}`;
});
