# Designing OCR and Transcript Correction Interfaces

UX patterns, real-world examples, and tooling for building a UI where humans
review and correct Optical Character Recognition (OCR) or Handwritten Text
Recognition (HTR) outputs. (Converted from the PDF "OCR Correction UX & Tools
Guide" — the transcription review surface 2026-08.)

Building such an interface bridges two very different mediums: **spatial visual
data** (scanned images, archival manuscripts) and **sequential textual data**
(plain or structured text). This guide covers core UX architecture patterns,
landmarks from real-world systems, and production-ready libraries.

## Part 1: Core UX Architecture Patterns

1. **Split-pane dual view.** The scanned original document image occupies one
   side of the screen (with high-performance pan/zoom), an editable text pane
   the other. It minimizes cognitive load by keeping the visual source and
   target output in constant spatial proximity.
2. **Line-by-line spatial alignment (bounding-box mapping).** Text breaks into
   discrete lines/blocks mapped via bounding boxes or segmentation polygons to
   physical lines on the scan. Clicking a text line highlights the
   corresponding image line (and vice versa) — users never lose their place in
   complex layouts, multi-column print, or fractured manuscripts.
3. **Confidence-driven visual cues.** The interface highlights low-confidence
   OCR words/characters (background colour tint, underlines) from the engine's
   output metrics, drawing human labour directly to error-prone areas.

## Part 2: Real-World Prior Art

- **Trove** (National Library of Australia) — one of the world's largest
  crowdsourced OCR-correction platforms for historical newspapers. A scanned
  clipping beside a raw text column; a "Match text" button opens a live cursor
  for inline editing with line-splitting and combining tools.
- **Transkribus** — a premier platform for historical manuscripts/archives.
  Automated layout analysis slices pages into line polygons mapped to a
  companion text editor, for rapid correction of machine text.
- **FromThePage** — a widely adopted collaborative transcription tool using
  IIIF standards, with robust version control, page-turn management, and
  inline annotation workflows.

## Part 3: Open-Source Libraries & Developer Tooling

### Frontend image viewing & overlays

- **OpenSeadragon** — the gold-standard open-source JavaScript deep-zoom image
  viewer; handles massive, multi-gigabyte archival TIFFs and high-resolution
  scans smoothly.
- **OpenSeadragonFabricOverlay** — integrates Fabric.js with OpenSeadragon for
  custom vector shapes, bounding boxes, and transcription polygons over
  document lines.

### Full-stack transcription & layout platforms

- **eScriptorium** — an open-source web app (Python/Vue.js) built for layout
  segmentation, baseline tracking, and manual text transcription correction;
  click line polygons to edit text.
- **Digirati IIIF Manifest Editor** — a modern JS tool for visually creating,
  editing, and managing IIIF manifests and inline canvas annotations.
