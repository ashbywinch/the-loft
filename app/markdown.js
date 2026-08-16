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

/** The inline format split — ~~struck~~ (crossed-out in the letter) and
 *  ~underlined~ (underlined in the letter, 2026-08-16) — the review's
 *  format conventions, rendered for the archive. Text nodes only, never
 *  HTML (the renderer's injection rule). */
function inlineParts(text) {
  const parts = [];
  const re = /~~([^~]+)~~|~([^~]+)~/g;
  let last = 0;
  let m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push({ text: text.slice(last, m.index), kind: null });
    parts.push({ text: m[1] ?? m[2], kind: m[1] !== undefined ? "struck" : "underlined" });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), kind: null });
  if (!parts.length) parts.push({ text, kind: null });
  return parts;
}

function inlineNodes(text) {
  return inlineParts(text).map((p) =>
    p.kind === "struck"
      ? el("span", { class: "fmt-struck" }, p.text)
      : p.kind === "underlined"
        ? el("span", { class: "fmt-underline" }, p.text)
        : p.text,
  );
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
        // a pipe line whose FOLLOWING line is a separator starts a NEW
        // table — the body stops here so the outer loop picks the next
        // table up instead of swallowing it (2026-08-11 review: two
        // adjacent tables merged — the second's header + separator were
        // consumed as the first's body rows)
        if (j + 1 < lines.length && /^\s*\|[\s:|-]+\|\s*$/.test(lines[j + 1])) break;
        tableLines.push(lines[j]);
        j++;
      }
      nodes.push(renderTable(tableLines));
      i = j;
      continue;
    }
    const para = [];
    const paraStart = i;
    // a pipe-prefixed line that failed the table check is still verbatim
    // text — include the current line, then stop at the next pipe line
    // (2026-08-09 review: a line like "| the boat's name |" was silently
    // dropped — the table branch skipped it, the paragraph loop refused it)
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      (i === paraStart || !PIPE.test(lines[i]))
    ) {
      para.push(lines[i]);
      i++;
    }
    // the transcription-text class makes the pre-line CSS apply everywhere
    // the renderer's paragraphs land, including the reader (2026-08-09
    // review: stories.js appended bare <p> nodes and the line breaks
    // collapsed again)
    if (para.length) nodes.push(el("p", { class: "transcription-text" }, inlineNodes(para.join("\n"))));
    else i++;
  }
  return nodes;
}
