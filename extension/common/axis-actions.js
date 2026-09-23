"use strict";

/** Select the per-axis ``absent`` controls through the page's own inputs. */
export async function selectAxisAbsences(rows, intercepts) {
  const ALLOWED_ORIGIN = "https://learn.hawkeslearning.com";
  if (window.location.origin !== ALLOWED_ORIGIN) {
    return { ok: false, code: "wrong-site" };
  }
  const axes = ["x", "y"];
  if (!Array.isArray(rows) || rows.length !== 2 || !intercepts) {
    return { ok: false, code: "answer-invalid" };
  }
  const nameOf = (radio) => {
    const direct = String(radio.getAttribute?.("aria-label") ?? "").trim();
    if (direct) return direct;
    const escape = globalThis.CSS?.escape;
    const label = radio.id && escape
      ? document.querySelector?.(`label[for="${escape(radio.id)}"]`)
      : radio.closest?.("label");
    return String(label?.textContent ?? radio.value ?? "").replace(/\s+/g, " ").trim();
  };
  let selected = 0;
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
      await new Promise((resolve) => setTimeout(resolve, 120));
    }
    if (radio.checked !== absent) {
      return { ok: false, code: "axis-option-not-settled", axis };
    }
    selected += absent ? 1 : 0;
  }
  return { ok: true, code: "axis-options-settled", selected };
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
