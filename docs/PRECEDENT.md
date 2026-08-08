# Precedent Scan Notes (D7) — Family History Album

Companion to `PRD.md` §17, step D7. What exists, what works, what to avoid. Sources at the end. Status: completed 2026-08-02.

## 1. Family-history platforms (Findmypast, Ancestry, FamilySearch)

**The anti-pattern is real and documented.** The tree-and-records model is built for expert genealogists; beginners drop off because onboarding requires a parallel curriculum *outside* the product (YouTube, genealogist friends). Ancestry's own post-mortem: "one experience cannot serve both expert and novice."

- **Lesson A — we are not a genealogy tool.** No tree view, no "records" browsing, no census-workflow. The moment the app smells like homework it dies. (Roadmap: tree view removed from Could. **Refined 2026-08-02:** the anti-pattern is the expert genealogy *tool* — records, census workflows, homework. A person-centred relationship view is a museum surface, not a genealogy tool — see §5.)
- **Lesson B — outcomes language, never task language.** Findmypast's UX case study: the word "task" reads as chore; framing everything as *discovery outcomes* ("find a relative", "hear their voice") beats instruction bars. Our capture ritual must say "save a story", never "complete metadata".
- **Lesson C — two experiences, one app.** Ancestry's fix was a separate opt-in novice path. Our IA already does this structurally: **Stories/Cast are the novice doors, Timeline/Search are the deep doors.** Home must front-door the novice path, or the 15-year-old lands in homework.

## 2. Google Photos Memories (the serendipity reference)

The most successful "on this day" product in existence. What it got right:

- **Serendipity as a story player, not a grid.** Memories present as an immersive, scrapbook-style story with movement and music — presentation is emotional, not utilitarian.
- **Controls are the trust layer.** Hide specific faces, hide date ranges, hide individual memories. Their research is explicit: some memories (funerals, painful moments) are upsetting, and user control is what makes nostalgia-features *safe* to use.
- **Scrapbook warmth.** Oval masks, collage layouts, AI titles — deliberately warm, not archival-clean.

- **Lesson D — serendipity needs boundaries.** On-this-day must be dismissible per date, per person, per memory. This family has raw dates (dementia is recent) — the D3-E privacy flags feed exactly this control. (Roadmap: memory controls added to Should.)
- **Lesson E — warm beats clean.** Rounded frames, handwriting-friendly type, quiet texture. A museum is warm; a database is clean. We choose museum.

## 3. Museum apps (SFMOMA, Cuseum guides)

The closest professional analog to "a walk through a collection with feelings."

- **Attention budgets are real.** SFMOMA: ~2 min per audio segment, 15–20 stops, ~30 min tours max. Visitors fatigue fast.
- **Lesson F — stories must be snackable.** 3–8 items per story, one-sentence connective captions, ~2–5 min to read. A story is an essay's worth of feeling, not a book.
- **Tonal range is a feature.** SFMOMA scripts deliberately span earnest → humorous → experimental, matched to the artwork. Not every story should be solemn — some of Mum and Dad's letters will be funny, and the app should let them be.
- **Accessibility is visitor-first:** high contrast, adjustable text size, text-to-speech. (Roadmap: text-to-speech added to Could — "hear the letter read aloud" also deepens the voices goal, G6.)
- **Analytics for drop-off** — we have none by privacy design; D8/D10 manual observation is the substitute, deliberately.

## 4. Synthesis — pattern language for this product

| Principle | Source | Where it lands in the PRD |
|---|---|---|
| Never homework | Findmypast, Ancestry | Anti-requirements (§9); no tree view (Roadmap) |
| Outcomes language | Findmypast | Capture ritual copy ("save a story") |
| Novice door vs. deep door | Ancestry | IA: Stories/Cast = novice, Timeline/Search = deep |
| Serendipity with controls | Google Photos | Memory controls (Should); D3-E flags feed it |
| Scrapbook warmth | Google Photos | §10 presentation note |
| Snackable stories | SFMOMA/Cuseum | §10 story sizing (3–8 items, 2–5 min) |
| Tonal range | SFMOMA | Stories may be funny or sad; never flattened |
| TTS accessibility | Cuseum/WCAG | Text-to-speech (Could) |
| Observation over analytics | Cuseum vs. privacy | D8/D10 manual testing |

## 5. Family tree UI patterns (added 2026-08-02)

Research question: are there established UI patterns for family trees, especially on mobile?

- **The whole-tree canvas is a desktop pattern.** Pan/zoom canvases (Gramps Graph View, kintales-tree-view, Ancestry) need pinch/drag gestures and viewport culling, and the research consensus is that dense branching is the readability killer. Mobile apps that ship a full canvas are the exception, and they still fight the screen.
- **The established mobile pattern is person-centred navigation.** Focus one person; show parents above, partner beside, children below; tap anyone to re-centre. Position encodes relationship — no connector lines needed. FamilySearch's mobile tree is built this way; bondar.design's redesign ("observe all relations on one level — avoid dense branching") and the BYU "My Relatives" paper (person-centred relationship listing) agree.
- **Pedigree and fan charts are ancestor-only.** Space-efficient for lineage, useless for descendants, siblings and in-laws — the wrong shape for a family whose story runs sideways.
- **Sequential single-view flows** (MEGGIE QU's guided tree builder) work for *building* a tree, not for browsing one.

**Decision (2026-08-02):** the whole-tree generation view is replaced by the person-centred view (`#/tree?person=<id>`): one person at the centre, parents above, partner beside, siblings and children below, wider relations (in-laws, teachers) as tags; tap a card to re-centre, the centre card opens the profile. Same data, better reading, zero new dependencies. (Our own first attempt — generation rows — failed exactly the way the research predicts: relationships were inferable only by counting rows.)

## Sources
- Findmypast task/reward UX case study — https://medium.com/@ryanconnaughton/task-reward-experiment-ux-case-study-for-findmypast-152a40c9755e
- Ancestry novice onboarding post-mortem — https://www.insidergrowthhq.com/p/how-ancestry-used-ai-to-unlock-a
- Google Photos People + AI Research: "A snapshot of AI-powered reminiscing" — https://medium.com/people-ai-research/a-snapshot-of-ai-powered-reminiscing-in-google-photos-5a05d2f2aa46
- Google Photos Memories launch (The Verge) — https://www.theverge.com/2019/9/12/20860938/google-photos-memories-prints-cvs-walmart-canvas
- SFMOMA location-aware storytelling paper — https://mw17.mwconf.org/paper/audio-that-moves-you-experiments-with-location-aware-storytelling-in-the-sfmoma-app/index.html
- Cuseum: museum apps, visitor-first strategies — https://cuseum.com/blog/mobile-apps-for-museums-strategies-and-trends-for-2025
- Family historian motivation research (MDPI) — https://www.mdpi.com/2313-5778/8/1/3
- FamilySearch Family Tree mobile — person-centred tree, portrait/fan views — https://www.familysearch.org/en/blog/updated-family-tree-android-app · https://www.familysearch.org/en/help/helpcenter/article/what-are-the-features-of-the-family-tree-and-memories-mobile-apps
- "My Relatives" — person-centred relationship listing (BYU FHTW) — https://fhtw.byu.edu/conf/2015/baker-closest-fhtw2015.pdf
- bondar.design Family Space redesign — single-level relation visibility — https://bondar.design/en/family-space
- kintales-tree-view — pan/zoom canvas reference (the desktop pattern) — https://github.com/MariyanYordanov/kintales-tree-view
- MEGGIE QU — guided tree builder case study — https://meggie-qu.com/onboarding.html
