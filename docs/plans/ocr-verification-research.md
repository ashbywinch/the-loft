# OCR verification — what the field knows and what we're missing

Research synthesis (2026-08-26), prompted by the user: "this is turning
out to be really difficult — research what other people have found out
about verifying OCR text and what we're missing about good solutions."

## 1. Confidence scores are the field's first tool — and we ignore ours

- Engine confidence correlates with word-error rate across engines on
  ~5M historical pages (1456–2000): confidence is a practical quality
  proxy where ground truth is unavailable or expensive.
  https://doi.org/10.63744/gr59c1ixu6wj
- Transkribus (the HTR standard): per-character/per-line confidence
  drives targeted human review; a 70–95% AI first draft plus a
  correction loop reaches high accuracy at scale (25k wills, 45min ->
  <10min per page).
  https://www.transkribus.org/crowdsourcing-transcription-platform

What we're missing: PaddleOCR gives per-detection confidence scores we
never read — a free text-likeness filter for the noise detections that
become empty-box rows. We BUILT the VLM self-report stage (the model
flags its least-sure words) and never wired it into the process; it is
exactly Transkribus's confidence-driven review, and the UI already
renders it ("red words are ones the machine wasn't sure of").

## 2. GT-free error prediction exists — and requires calibration

- WER can be predicted without ground truth by CALIBRATING a naive
  estimate against a small labeled sample (naive estimates are
  systematically optimistic; calibration lands within ~1.7 absolute
  WER points). https://doi.org/10.1007/s10032-026-00578-6
- MLM-based GT-free metrics correlate with CER and beat naive
  confidence. https://aclanthology.org/2022.lrec-1.467.pdf

What we're missing: every gate constant (the 0.12 density floor, the
1.7 ceiling, has_ink's -35, the 2.5 tall-split factor) is an
UNCALIBRATED guess tuned by incident. The eval contract
(test_eval_postcard) has been blocked for three sessions. The field's
answer: settle a small labeled truth set, then measure and tune the
gates against it. Five to ten vision-verified pages would calibrate
everything we built.

## 3. Multi-engine agreement is the consensus signal — with caveats

- Naive engine voting is unreliable (confidence scales differ, an
  overconfident engine can dominate). https://community.aiim.org/blogs/chris-riley%20ecmp%20ioap/2010/10/26/campaigning-characters-%E2%80%93-reality-of-ocr-engine-voting
- Consensus Entropy (2026): with MULTIPLE VLMs, correct outputs
  cluster, errors disperse — disagreement entropy is a quality metric,
  and disagreement routes to a stronger model. CVPR 2026.
  https://arxiv.org/html/2504.11101v4

What we're missing: we have TWO independent readers of the same ink —
the rec (local, character-level) and the VLM (cloud, contextual). The
"label verification" micro-step (accept a label only when the row's own
rec-read overlaps the assigned line; else flag) was designed in the
2026-08-22 architecture pass and never built. It IS Consensus Entropy,
with a stronger independence claim than two correlated VLMs. The
ladder's fallback models give us the "route to stronger model" half.

## 4. VLM transcription faithfulness is a real, characterized failure — and we've seen it

- "Do VLMs Read or Rewrite?" (2026): VLMs REWRITE imperfect text into
  plausible form; short words most (up to ~10%), non-local effects (5%
  perturbation inflates errors elsewhere 2-5x); general VLMs degrade
  most, OCR-specialized VLMs less, TRADITIONAL OCR is most faithful on
  English. https://arxiv.org/html/2607.21617v1
- PAR (training-free): positional perturbation + attention recycling
  reduce linguistic-prior hallucination, ~12% CER cut in long context.
  https://aclanthology.org/2026.acl-long.1065/
- "When Low CER is Not Enough" (historical Uruguayan docs): standard
  CER hides qualitatively distinct hallucination classes — the
  "metrics pass, document is wrong" problem exactly.
  https://arxiv.org/pdf/2607.24077

What we're missing: our observed misreads ("No pears eh! Huh!" vs the
handwriting's "No peace eh! Huh!") are the documented rewriting class.
The uncomfortable implication for our architecture: we made the VLM the
sole transcriber because it reads cursive, but the literature says its
characters are the LEAST faithful layer. The reconciliation is
per-word agreement: where the rec read something different from the
VLM's transcription, the VLM may have rewritten — flag it (the
verification micro-step again).

## 5. Line segmentation is a mature benchmarked task

- ICDAR handwriting segmentation contests (2009/2013/2017/2025):
  per-line IoU, precision/recall, 95% overlap acceptance thresholds;
  best systems reach ~0.96 line IoU. The DIVA evaluator visualizes
  per-line precision/recall color-coded — the same idea as our contact
  sheets, standardized since 2017.
  https://github.com/DIVA-DIA/DIVA_Line_Segmentation_Evaluator
  https://arxiv.org/html/2509.12965v1

What we're missing: the fragment-box false pass (071639) is a line-
segmentation RECALL failure — precisely what the ICDAR metrics
formalize (a box must overlap its true line ~95%). Our proposed
ink-extent gate (box width vs its band's contiguous ink run) is the
GT-free form of that metric. A small labeled set turns the contact
sheets into real per-line precision/recall numbers.

## 6. The correction loop should feed back (Transkribus pattern)

The review surface already stores user edits (VR9) — a growing labeled
sample that today goes nowhere. Transkribus's accuracy gains come from
retraining on corrections; at minimum, our edits should flow into the
calibration set and the eval harness.

## Priority order, grounded in the above

1. Wire the self-report stage (built, unplugged; Transkribus pattern;
   near-zero cost; uses a confidence signal we already produce).
2. The rec-agreement label check (Consensus Entropy with two
   independent readers; catches the rewriting class we hit
   empirically — "No peace eh!").
3. Settle the eval contract with a small labeled truth set (5-10
   vision-verified pages) and CALIBRATE the gate constants against it
   instead of tuning by incident.
4. The fragment-box ink-extent gate (GT-free line-IoU recall).
5. Route review edits into the labeled set so the calibration grows.
