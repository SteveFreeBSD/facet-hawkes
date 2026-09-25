export function labeledCoordinateAnswer(points, rows) {
  if (!Array.isArray(points) || !Array.isArray(rows) || points.length < 2
    || points.length > 12 || rows.length !== points.length
    || new Set(points.map((point) => point?.label)).size !== points.length
    || new Set(rows.map((row) => row?.label)).size !== rows.length
    || points.some((point) => !/^\S{1,16}$/.test(point?.label ?? "")
      || ![point.x, point.y].every((value) => typeof value === "string"
        && value.length <= 40 && /^-?\d+(?:\/[1-9]\d*)?$/.test(value))
      || !rows.some((row) => row.label === point.label))) return null;
  return points.map((point) => `${point.label}: (${point.x},${point.y})`).join("; ");
}

/** Read explicit page-owned label/axis associations, never field order. */
export function labeledCoordinateSurface(expected = null) {
  const fields = [...document.querySelectorAll('input[id^="txtAns"][id$="_num"]')].filter((field) => {
    const rect = field.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && !field.disabled;
  });
  const rows = new Map();
  if (fields.length < 4 || fields.length > 24) return { ok: false, code: "labeled-coordinate-fields" };
  if (new Set(fields.map((field) => field.id)).size !== fields.length) return { ok: false, code: "labeled-coordinate-duplicate-id" };
  for (const field of fields) {
    const names = (field.getAttribute("aria-labelledby") ?? "").split(/\s+/)
      .filter((id) => id && id !== field.id).map((id) => document.getElementById(id))
      .filter(Boolean).map((node) => String(node.textContent ?? "").trim());
    const matches = names.map((name) => /^point\s+(\S{1,16})\s+(first|second|x|y)\s+coordinate$/i.exec(name)).filter(Boolean);
    if (matches.length !== 1 || !field.id) return { ok: false, code: "labeled-coordinate-identity" };
    const [, label, axis] = matches[0];
    if (names.some((name) => { const prefix = /^(\S{1,16})\s*:/.exec(name); return prefix && prefix[1] !== label; })) {
      return { ok: false, code: "labeled-coordinate-conflict" };
    }
    const row = rows.get(label) ?? { label, x: "", y: "" };
    const key = /^(first|x)$/i.test(axis) ? "x" : "y";
    if (row[key]) return { ok: false, code: "labeled-coordinate-duplicate" };
    row[key] = field.id;
    rows.set(label, row);
  }
  const result = [...rows.values()].sort((a, b) => a.label.localeCompare(b.label));
  if (result.some((row) => !row.x || !row.y)) return { ok: false, code: "labeled-coordinate-incomplete" };
  if (expected && JSON.stringify(result) !== JSON.stringify(expected)) return { ok: false, code: "labeled-coordinate-changed" };
  return { ok: true, rows: result };
}
