"use strict";

/** Select the per-axis ``absent`` controls through the page's own inputs. */
export async function selectAxisAbsences(rows, intercepts, family = "axis", verifyOnly = false) {
  const ALLOWED_ORIGIN = "https://learn.hawkeslearning.com";
  if (window.location.origin !== ALLOWED_ORIGIN) {
    return { ok: false, code: "wrong-site" };
  }
  if (family === "graph-domain-range") {
    if (!Array.isArray(rows) || rows.length !== 2 || new Set(rows.map(r=>r.role)).size !== 2
      || !intercepts || Object.keys(intercepts).sort().join() !== "domain,range") return {ok:false,code:"answer-invalid"};
    const targets=[];
    for (const row of rows) {
      const radio=document.getElementById(row.optionId), field=document.getElementById(row.fieldId);
      const owner=document.getElementById(row.ownerId), fieldset=radio?.closest?.("fieldset");
      const legends=fieldset ? [...fieldset.children].filter(n=>n.tagName.toLowerCase() === "legend") : [];
      const label=String(radio?.getAttribute("aria-labelledby") ?? "").trim().split(/\s+/)
        .map(id=>document.getElementById(id)?.textContent ?? "").join(" ").trim().toLowerCase();
      if (!(radio instanceof HTMLInputElement) || radio.type !== "radio" || !radio.classList.contains("opt")
        || radio.disabled || !radio.getClientRects().length || label !== "all real numbers"
        || radio.name !== row.group || String(radio.getAttribute("aria-controls") ?? "").trim() !== row.ownerId
        || !(field instanceof HTMLInputElement) || !owner?.contains(field) || !fieldset?.contains(field)
        || legends.length !== 1 || String(legends[0].textContent ?? "").trim().replace(/:$/, "").toLowerCase() !== row.role
        || fieldset.querySelectorAll('input[type="radio"].opt').length !== 1
        || !["domain","range"].includes(row.role)
        || !["all-real-numbers","singleton","interval"].includes(intercepts[row.role]?.kind)) return {ok:false,code:"axis-surface-changed"};
      const wanted=intercepts[row.role].kind === "all-real-numbers";
      if (!wanted && (radio.checked || field.disabled)) return {ok:false,code:"axis-option-not-settled"};
      targets.push({radio,field,wanted});
    }
    if (new Set(targets.map(t=>t.radio)).size !== 2 || new Set(targets.map(t=>t.field)).size !== 2) return {ok:false,code:"axis-surface-changed"};
    let events=0;
    for (const {radio,wanted} of targets) {
      if (!verifyOnly && wanted && !radio.checked) {
        radio.dispatchEvent(new MouseEvent("click",{bubbles:true,cancelable:true,view:window}));
        events += 1;
        await new Promise(resolve=>setTimeout(resolve,120));
      }
      if (radio.checked !== wanted) return {ok:false,code:"axis-option-not-settled"};
    }
    if (targets.some(({radio,wanted})=>radio.checked !== wanted)) return {ok:false,code:"axis-option-not-settled"};
    return {ok:true,code:"axis-options-settled",selected:targets.filter(t=>t.wanted).length,events};
  }
  const axes = ["x", "y"];
  if (!Array.isArray(rows) || rows.length !== 2 || !intercepts) {
    return { ok: false, code: "answer-invalid" };
  }
  const nameOf = (radio) => {
    const direct = String(radio.getAttribute?.("aria-label") ?? "").trim();
    if (direct) return direct;
    const owner = String(radio.getAttribute?.("aria-labelledby") ?? "")
      .split(/\s+/)
      .filter(Boolean)
      .map((id) => document.getElementById(id))
      .filter(Boolean)
      .map((node) => String(node.textContent ?? "").trim())
      .filter(Boolean)
      .join(" ");
    if (owner) return owner;
    const escape = globalThis.CSS?.escape;
    const label = radio.id && escape
      ? document.querySelector?.(`label[for="${escape(radio.id)}"]`)
      : radio.closest?.("label");
    return String(label?.textContent ?? radio.value ?? "").replace(/\s+/g, " ").trim();
  };
  let selected = 0;
  let events = 0;
  for (const axis of axes) {
    const row = rows.find((item) => item?.axis === axis);
    if (
      !row
      || !Array.isArray(row.fieldIds)
      || row.fieldIds.length !== 2
      || typeof row.optionId !== "string"
    ) {
      return { ok: false, code: "axis-surface-changed" };
    }
    const radio = document.getElementById(row.optionId);
    if (
      !(radio instanceof HTMLInputElement)
      || radio.type !== "radio"
      || !radio.classList.contains("opt")
      || radio.disabled
      || nameOf(radio).toLowerCase() !== "absent"
    ) {
      return { ok: false, code: "axis-surface-changed" };
    }
    const absent = intercepts[axis] === null;
    if (absent && !radio.checked) {
      // This is the page-owned answer control itself.  No generic button is
      // clicked and no selector can reach Submit/Check/Next/Skip.
      radio.dispatchEvent(new MouseEvent("click", {
        bubbles: true,
        cancelable: true,
        view: window,
      }));
      events += 1;
      await new Promise((resolve) => setTimeout(resolve, 120));
    }
    if (radio.checked !== absent) {
      return { ok: false, code: "axis-option-not-settled", axis };
    }
    selected += absent ? 1 : 0;
  }
  return { ok: true, code: "axis-options-settled", selected, events };
}

/** Read back both radio state and coordinate fields after the page settles. */
export async function verifyAxisInterceptInsertion(rows, intercepts) {
  if (window.location.origin !== "https://learn.hawkeslearning.com") {
    return { ok: false, code: "wrong-site" };
  }
  await new Promise((resolve) => setTimeout(resolve, 400));
  let fields = 0;
  let absent = 0;
  for (const axis of ["x", "y"]) {
    const row = rows.find((item) => item?.axis === axis);
    const radio = row && document.getElementById(row.optionId);
    const boxes = Array.isArray(row?.fieldIds)
      ? row.fieldIds.map((id) => document.getElementById(id))
      : [];
    if (
      !(radio instanceof HTMLInputElement)
      || radio.type !== "radio"
      || boxes.length !== 2
      || boxes.some((box) => !(box instanceof HTMLInputElement))
    ) {
      return { ok: false, code: "axis-surface-changed" };
    }
    const point = intercepts[axis];
    if (point === null) {
      if (!radio.checked || boxes.some((box) => String(box.value ?? "") !== "")) {
        return { ok: false, code: "axis-readback-failed", axis };
      }
      absent += 1;
      continue;
    }
    if (
      radio.checked
      || !Array.isArray(point)
      || point.length !== 2
      || boxes.some((box, index) => String(box.value ?? "") !== point[index])
    ) {
      return { ok: false, code: "axis-readback-failed", axis };
    }
    fields += 2;
  }
  return { ok: true, code: "axis-intercepts-verified", fields, absent };
}
