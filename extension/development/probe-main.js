"use strict";

// Development-only MAIN-world diagnostic.  Every operation below is a
// property read or a bounded graph read accessor. Other functions are named
// but never invoked except for Knockout observables' zero-argument read form.
(() => {
  const ui = window.quant_wp_UI;
  if (!ui || typeof ui !== "object") {
    return { ok: false, code: "quant-ui-missing" };
  }
  const MAX_KEYS = 200;
  const MAX_STRING = 3000;

  const metadata = (source, depth = 0) => {
    const properties = {};
    const methods = [];
    let names = [];
    try {
      names = Object.getOwnPropertyNames(source ?? {}).sort().slice(0, MAX_KEYS);
    } catch {
      return { type: "unreadable", properties, methods };
    }
    for (const name of names) {
      let value;
      try {
        value = source[name];
      } catch {
        properties[name] = { error: "unreadable" };
        continue;
      }
      if (typeof value === "function") {
        let observable = false;
        try {
          observable = Boolean(window.ko?.isObservable?.(value));
        } catch {
          observable = false;
        }
        if (!observable) {
          methods.push(name);
          continue;
        }
        try {
          value = value();
        } catch {
          properties[name] = { observable: true, error: "unreadable" };
          continue;
        }
      }
      if (value === null || ["boolean", "number"].includes(typeof value)) {
        properties[name] = value;
      } else if (typeof value === "string") {
        properties[name] = value.slice(0, MAX_STRING);
      } else if (
        Array.isArray(value)
        && value.length <= 60
        && value.every((item) => item === null || ["boolean", "number", "string"].includes(typeof item))
      ) {
        properties[name] = value.map((item) =>
          typeof item === "string" ? item.slice(0, 500) : item
        );
      } else if (depth < 1 && value && typeof value === "object") {
        properties[name] = metadata(value, depth + 1);
      }
    }
    return {
      type: String(source?.constructor?.name ?? typeof source),
      properties,
      methods: methods.slice(0, 160),
    };
  };

  const values = (collection) => {
    try {
      return Object.values(collection ?? {}).slice(0, 60);
    } catch {
      return [];
    }
  };
  const relevantGlobals = {};
  for (const name of Object.getOwnPropertyNames(window)
    .filter((key) => /answer|question|valid|control|template|practice|session/i.test(key))
    .sort().slice(0, 160)) {
    try {
      relevantGlobals[name] = metadata(window[name]);
    } catch {
      relevantGlobals[name] = { type: "unreadable" };
    }
  }

  const graphModels = values(ui.controlsCollection).filter((item) => item?.isGraph === true);
  const graph = graphModels.length === 1 ? graphModels[0] : null;
  const graphEvidence = graph ? {
    xml: String(graph.graphXML?.() ?? "").slice(0, 20000),
    answer: String(graph.userAnswer?.() ?? "").slice(0, 20000),
    points: values(graph.allGraphObjects?.()).map((item) => metadata(item)),
    anchors: [...document.querySelectorAll('#QGraph a[draggable="true"][role="button"]')]
      .slice(0, 12).map((anchor) => ({id: anchor.id,
        labelledBy: anchor.getAttribute("aria-labelledby"),
        label: (anchor.getAttribute("aria-labelledby") ?? "").split(/\s+/)
          .map((id) => document.getElementById(id)?.textContent ?? "").join(" ").trim()})),
  } : null;

  return {
    ok: true,
    code: "development-contract-probed",
    ui: metadata(ui),
    graph: graphEvidence,
    controls: values(ui.controlsCollection).map((item) => metadata(item)),
    controlData: values(ui.controlsCollectionData).map((item) => metadata(item)),
    qdy: values(ui.QDyTextBoxObjects).map((item) => metadata(item)),
    relevantGlobals,
    fields: [...document.querySelectorAll("input, [contenteditable='true']")]
      .filter((element) => element.getClientRects().length > 0)
      .slice(0, 60)
      .map((element) => ({
        tag: element.tagName,
        id: element.id || "",
        name: element.getAttribute("name") || "",
        role: element.getAttribute("role") || "",
        inputType: element.getAttribute("type") || "",
        ariaLabel: element.getAttribute("aria-label") || "",
        ariaDescribedBy: element.getAttribute("aria-describedby") || "",
        value: String(element.value ?? "").slice(0, 80),
        ownerNames: (element.getAttribute("aria-labelledby") ?? "").split(/\s+/).filter((id) => id && id !== element.id).map((id) => document.getElementById(id)?.textContent ?? ""),
        attributes: Object.fromEntries(
          [...element.attributes].slice(0, 50)
            .map((attribute) => [attribute.name, attribute.value.slice(0, 500)])
        ),
      })),
    visibleMessages: [...document.querySelectorAll("[role='alert'], .alert, .validation-summary-errors")]
      .filter((element) => element.getClientRects().length > 0)
      .map((element) => String(element.textContent || "").trim().slice(0, 1500)),
  };
})();
