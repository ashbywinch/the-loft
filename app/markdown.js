/** A tiny markdown renderer for the transcriptions (2026-08-08, user: a
 *  medal index card is a table — the site must render the structure, not a
 *  run-on paragraph). The app has no runtime dependencies (TECH-SPEC §15),
 *  so this is in-house and deliberately small: pipe tables + paragraphs.
 *  The transcription data keeps the markdown verbatim; the renderer turns
 *  it into DOM nodes (text nodes only — no HTML injection from the data).
 */

import { el } from "./ui.js";

const PIPE = /^\s*\|/;

function splitRow(line) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function renderTable(lines) {
  const rows = lines.map(splitRow);
  const table = el("table", { class: "transcription-table" });
  const head = el("thead");
  head.append(el("tr", {}, rows[0].map((cell) => el("th", {}, cell))));
  table.append(head);
  const body = el("tbody");
  for (const row of rows.slice(2)) {
    body.append(el("tr", {}, row.map((cell) => el("td", {}, cell))));
  }
  table.append(body);
  return table;
}

/** Markdown -> DOM nodes: a pipe table (header + |---| separator + body)
 *  becomes a <table>; everything else stays a <p> with the newlines intact
 *  (the pre-line CSS renders them). The separator row is what marks a table,
 *  so an ordinary line containing pipes is never misread as one. */
export function renderMarkdown(text) {
  const lines = String(text ?? "").split("\n");
  const nodes = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (PIPE.test(line) && i + 1 < lines.length && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1])) {
      const tableLines = [line];
      let j = i + 1;
      while (j < lines.length && PIPE.test(lines[j])) {
        tableLines.push(lines[j]);
        j++;
      }
      nodes.push(renderTable(tableLines));
      i = j;
      continue;
    }
    const para = [];
    while (i < lines.length && lines[i].trim() !== "" && !PIPE.test(lines[i])) {
      para.push(lines[i]);
      i++;
    }
    if (para.length) nodes.push(el("p", {}, para.join("\n")));
    else i++;
  }
  return nodes;
}
