# Story & Fact Capture — "Add your memory"

- **Status:** plan — approved shape (2026-08-03); **slices 0–3 shipped** (read side, capture server, AI elicitation, write path), plus the chat redesign, review toggles, dob-aware dating, artifact links, and the identity correction (`p-alex`; curation is a role, not a person)
- **Companions:** `PRD.md` §19 (story harvest), `TECH-SPEC.md` §16.9/§16.11/§16.12, `../plans/PLAN.md`
- **Note:** the §16 sections live on the `phase-1-import-flow` branch; this plan assumes they land.

## What this is

Browse-side capture (PRD §19, productized): every entity page — item, person,
place, story/theme — carries an **"Add your memory"** affordance. A contributor
tells their account; an AI assesses it — extracting proposed people/places/links
per the §16.9 four buckets and running the §16.9 cross-checks — then interviews:
**open-ended first** ("anything else?") until the narrator closes the account,
then **bounded targeted questions** for genuinely missing detail. The narrator
reviews before anything is stored. The AI's guesses — links, dates, facts —
are verified by whoever is operating the flow, in the same flow's review:
kept means confirmed, dropped means gone, nothing waits on a separate
confirmation gate. Nothing asserted unreviewed (P4); nothing told is lost
(§19.4).

## Grounding

- **The four buckets & cross-checks** (TECH-SPEC §16.9): Identified / Proposed /
  Question / Unresolved; chronology, standing cast, precision, actuality-not-
  recurrence, co-occurrence ≠ relationship, presence attribution, ask-don't-guess.
  The 2026-08-03 bug family (Wilma/Miles at Dunmoor; Fern at none of the 1977
  letter's places; Eli "proposed" before birth) is the machine's checklist.
- **Interview-module requirements** (PRD §19, reqs 1, 4–10): narrator review pass
  before storage; questions surface on entity pages; prod for dates with honest
  precision; ask who was present; polite dob/pronouns only when they disambiguate;
  informal/referential places; uncertain locations askable.
- **Display order is product law** (§19.7): artifact/facts first, the reader's own
  testimony next, other people's testimony last.
- **Stealable AI client:** `books_to_anki/src/book_to_flashcards/opencode_translator.py`
  — self-contained urllib client for `https://opencode.ai/zen/go/v1`
  (`deepseek-v4-flash`): `find_api_key()` (env `OPENCODE_API_KEY` → opencode
  `auth.json`), retry/backoff on 429/5xx, thinking-disable fallback,
  `response_format: json_object`, injectable `urlopen` for tests, strict JSON
  parsing with recovery. Its tests (`test/src/test_opencode_translator.py`) are
  the template for ours.
- **Current branch:** static vanilla app, no backend, no `comment_on` rendering
  yet, secrets are shell-env-only. §16.11 establishes the localhost-only server +
  "server not reachable" degradation card. Data shapes: items carry
  `story`/`told_by`/`status`; people carry `aliases` (the resolution seam).

## Architecture

```
entity page (item / person / place / theme)
  → "Add your memory" sheet (compose)
  → POST /api/contributions     (localhost loft server, §16.11 shape)
  → assess + elicit             (OpenCode client, env key, never in the browser)
  → review screen               (verbatim + proposed links, redact before save)
  → local archive               (sidecar + story.txt content file — status
                                 catalogued when verified in the review,
                                 draft when abandoned; same store as the app's info)
  → publish (regenerate app/data) → browse app
```

- The AI **never runs in the browser**: keys live in the shell env on the
  household machine (house rules; §7 — no third-party cloud processing of family
  content; the LLM call itself is the explicitly requested shell-out, and the
  client is the household server).
- The deployed static site renders the affordance; without the server it shows
  the same graceful card as the import admin view (§16.11).

## Data model

New item type `story` — a memory is not a new kind of thing; it is a story
(user, 2026-08-03). The model is the import branch's, canonically
`story-anns-account-1977` (17 story items there). A told account is an artifact
like any other (§19.5):

```json
{
  "id": "story-2026-08-03-01",
  "type": "story",
  "title": "Christmas at Marlock, 1965",
  "date": "1965-12-25",          // the events, honest precision (F1)
  "date_precision": "exact",
  "recorded": "2026-08-03",      // when told (PRD §19.2)
  "story": "<verbatim assembled account, all answers>",
  "told_by": "p-alex",
  "comment_on": null,             // item id when responding to an artifact or another story
  "people":  [{ "id": "p-owen", "status": "proposed" }],
  "places":  [{ "id": "pl-marlock", "status": "proposed" }],
  "themes":  [{ "id": "t-the-boats", "status": "proposed" }],
  "source": "Site contribution, 2026-08-03",
  "status": "draft",
  "provenance": "Contributed via the site; narrator-reviewed; AI guesses verified in the review.",
  "created": "2026-08-03"
}
```

- **`date` = the events, `recorded` = when told** (F1, user 2026-08-03): the
  timeline places the memory with its subject matter, and the §16.9
  presence/chronology checks use the events' date. Precision is honest when the
  narrator cannot say (PRD req 5). **The date is never defaulted to the
  telling day**: the flow always asks for the events' date (a non-skippable
  question) and never fabricates `recorded` as the date; a story whose date
  equals its recorded/created stamp is a bug unless the narrator's own words
  stated the events happened that day — a diary-style entry (2026-08-05: the
  assessor fabricated telling-day dates, four stories shipped with them, and
  the moment card served "0 years ago this week" — enforced in elicitation
  and guarded by tests/test_story_dates.py, which requires the narrator's
  date answer in the transcript for any told-day date).
  The branch's seed stories re-point their dates on merge.
- **Not every story is an account — clarification fragments and reflections
  are story-shaped records with a flag, not a new type (2026-08-06).**
  - **Clarification** (`clarification: true`): an identity fact answered in
    the flow ("yes BF means Owen", "Lex is an alias of Alex"). It must
    name what it attests (people/items refs — the BF fragment also attests
    the 1977 letter). It has no events' date and renders **only on the pages
    it attests** (a "Clarifications" block on the person/item page), never on
    the timeline.
  - **Reflection** (`reflection: true`): the narrator's perspective ("meeting
    her" — how busy her social life was when I knew her). It has **no events'
    date other than the telling day** — its `date` is its `recorded` day —
    and it renders **only on the pages it mentions** (people/places refs, a
    "Reflections" block), never on the timeline.
  - A story is one or the other, never both; each must reference its target.
  - **The discovery seam is one function**: `published(items)` = catalogued
    minus clarification/reflection — the timeline, home, search, letters,
    museum, places and themes all read through it; fragments/reflections are
    found only via their blocks (a view that filters the flags itself is a
    finding, the same rule as statuses).
- **`comment_on` is a string item id** (F2, user 2026-08-03): a story responds
  to an artifact or another story (story ids are item ids — "about other
  people's stories" works). People/places/themes link through the normal
  `people[]`/`places[]`/`themes[]` refs and surface on those pages via the
  aggregates (§19.4). The page the narrator started from becomes a `proposed`
  ref — tapping "Add a memory of Nora" is the narrator's own aboutness
  evidence.
- **`type: "story"` is the told account itself** — distinct from themes, the
  curated "Themes" doors in `themes.json`; a story item embeds into a theme
  like any other item. Display reads a told account as **"Memory"** (with its
  "told by / told <date>" stamp on every card) — never "Story", which read
  like another scanned document to a visitor (user, 2026-08-03). The data
  type stays `story`; `typeLabel` is the one naming seam.
- **A story is a person's own words, verbatim — never generated testimony**
  (PRD §10, user 2026-08-03). The import flow's "seed stories" (the flat
  hunt, Sundown gigs, Grand Union — synthesized from the letters and
  prefixed "Alex:") were hallucinations presented as the narrator's words;
  they were removed from the projection, and no generated content is ever
  attributed a `told_by`. A story enters only through the capture flow
  (verbatim) or a human-verified import; an AI's summary is curation prose,
  never narrator testimony.
- **Facts are stories too** (F3, user 2026-08-03): a terse fact ("her birthday
  was 12 March 1928") is a verbatim story item; the AI's extraction proposes
  entity-field updates (dob, aliases, relationships, place precision) as
  review items alongside refs. The story stays as the
  attributed evidence — the worksheet's learn step (§16.9).
- **Verification is the review, not a later gate** (user, 2026-08-03): every
  AI guess enters `proposed` and the operator flips it in the same flow's
  review — kept = `confirmed`, dropped = gone. A completed, reviewed save is
  `catalogued` with `confirmed` refs; an abandoned one stays `draft` with
  `proposed` refs (nothing asserted unreviewed, P4). Presence attribution is
  per-place (§16.9): a story's `places[]` belongs to the story's own claim,
  never the co-mention.
- **`told_by` resolves through the alias seam** (`app/people.js`): the
  contributor names themselves; matched against the cast; no match → a `proposed`
  person record, never a silent merge. The name field autocompletes over the
  cast (names + aliases) so the right person is one tap; a name that matches
  nobody is assumed to be a **new person** — the assistant says so, and the
  assessment asks how they are connected to the family (unless the story
  already makes it obvious); the connection is recorded on the new person.
- **Auth (when accounts land, PRD §15): the narrator defaults to the current
  logged-on user** — the sheet pre-fills it. It stays changeable: the
  in-the-moment use case is the current user showing the app to someone IN the
  story, who remembers something interesting — the account is the guest's, and
  the autocomplete picks them from the cast or starts a new person.

- **Orgs and memorabilia are story links too (2026-08-05):** a story may
  reference organisations (`orgs[]`) and objects/memorabilia (`items[]` —
  an attested object, a thing the story names) — the same propose/confirm
  refs as people/places, validated at publish. One content model, two
  capture flows (docs/prd/IMPORT-PRD.md §2.5); the elicitation's extraction
  kinds gain `org`.
- **A known object family is disambiguated, never guessed (2026-08-06):**
  when an account references a family of known objects without naming one
  ("we were on the boat", "at the yard"), the flow asks which — "Which
  boat?" — rather than assuming. The bucket-hoisting story happened on
  *Sunlight*, and the flow never asked; the wrong object was referenced as a
  result. An object link is an assertion; the name comes from the narrator,
  not the model. Every object must be attested by an artifact that names it
  (guarded by tests/test_completeness — the viola was removed because no
  letter, story or transcription mentions any instrument).

## The elicitation protocol (the AI's job)

Two phases, one deterministic prompt per phase (JSON out, temperature 0, the
books_to_anki retry/splice discipline).

**Phase A — open-ended closure.** After the initial account: "Anything else?" —
up to two rounds, then a soft "anything else before we go on?". The narrator
closes with a one-tap **"That's everything"** in the UI, so open-endedness never
becomes a wall. The account is only finished when the narrator says so — never
cut short by structured questions (§19: capture fully, then review).

**Phase B — targeted gaps.** Given the account + the thing it's about + standing
cast/places/themes, ask *only* questions that meet the Question-bucket rules —
never filler, never what's already known:

- dates: prod, record precision honestly when the narrator can't say (req 5)
- who was actually present (req 8), with the §16.9 date-bounded presence check
- identity: "which Harper?" — never guessed (worked-example lesson 5)
- place identification/precision: "the old ford — which one?" (reqs 6–7)
- dob/pronouns only when they'd disambiguate presence, politely, nothing required (reqs 9–10)

Every question is skippable ("Don't know / Skip"); the set is bounded (~5,
progress shows "2 of 5"). Ambiguity → a question, never a proposal; every
proposal is `proposed`.

**Output contract:** `{extractions: [{kind, name, match: existing-id|null,
bucket, reason}], questions: [{text, why, skippable}]}` — plus entity-field
proposals (dob, aliases, relationships, place precision) entering the review
(F3).

## UI design

**Affordance placement** — one shared component (`app/contributions.js`),
identical on all four page types, obeying §19.7 (after the artifact/facts,
before Connections):

| Page | Placement |
|---|---|
| Item lens | after story/provenance/metadata → "Your memories": attributed responses, then the button |
| Person page | after bio/known-as → "Add a memory of Nora" |
| Place page | after the note → "Add a memory of Marlock" |
| Story/theme page | after the arranged items → "Add your story to this theme" |

Bottom-of-page, not topbar: the artifact is the anchor on a browse-first surface;
capture is the secondary act. Same 44px-touch, scrapbook-warm language as the
existing doors. A global "tell us a story" door on Home is out of scope (the
requirement starts from the thing's page) — candidate for later.

**The gathering flow** — a full-screen chat with the assistant (phone-first):

1. **Who**: the narrator IS the signed-in Google identity (2026-08-06) —
   the capture flow never asks for a name; signed out, it asks the narrator
   to sign in. The server mints `told_by` from the verified session — the
   old name-claim field and the localStorage narrator are gone. The
   assessment still matches people/places in the account against the cast.
2. **The account**: "What do you remember about X?" — the story, then
   "Anything else?" **with no cap** — the assistant keeps asking until the
   narrator taps "That's everything". Nothing is forced; nothing is lost.
3. **Questions**: the AI's targeted questions one at a time, each with
   quick-reply suggestion buttons, "Skip", and "I'd rather not say". The
   current question is always above the fold (no long transcript pushes it
   off-screen).
4. **Review**: the AI-suggested title, the assembled verbatim account
   (editable — redaction), and the proposed links as **toggles** (tap to keep
   or drop) plus an "add a person or place" field. Save as told.
5. **Saved**: confirmation — a draft, marked not confirmed.

The **assessment self-corrects** in the production call: the assessor's output
is reviewed by a second cheap pass, and genuine violations (mentions linked,
impossible matches, redundant questions, missing polite date questions) are
fed back for a bounded redo — never sampling-twice-and-picking. Dates from an
given age + a known date of birth are computed in deterministic code and
injected as "derived", so the model is never asked to do the arithmetic.
The review pass and the evals cover the family's own stories AND a fictional
*family (`tools/eval_elicitation.py`, `make evals`) so nothing is overfit to one
household. Identity: **no person is special-cased in code** — the narrator
resolves against the cast like anyone else, and curation is a role anyone can
hold, not a person record. (The prototype's seed cast happens to include
Alex Hale; the code never depends on it.)

**Degradation:** server unreachable → the sheet explains contributions are
collected when the household server is running (same card language as the import
admin view); the affordance stays visible.

## Write path — local now, hosted later (user, 2026-08-03)

Contributions land **wherever the app stores its info** — locally today, hosted
later. Locally that is the archive folder: the server writes story sidecars
(`assets/<id>/item.json`) at the archive path from the one seam
(`tools/loft_paths.py` — the big disk's `Loft/archive`, a sibling of the user's `scans` folders)
through the append-only store
(`tools/store.py`), then refreshes the projection (`app/data`) so the story
renders. **The story text is primary content**: the save path writes it as a
content file (`story.txt`) the sidecar references — never a sidecar JSON
field — and the projection embeds it again at publish (docs/TECH-SPEC.md §3,
"Primary vs derived"). **There is no separate confirmation gate** (user,
2026-08-03): the operator verifies the AI's guesses in the same flow's
review, so a completed save is `catalogued` with `confirmed` refs and is live
immediately; an abandoned session saves as `draft` with `proposed` refs. The
committed projection's invariant is self-describing items with a known status
(`catalogued` or `draft`, the 2060 test), not "everything catalogued".

**Append-only (requirement, 2026-08-03, content files 2026-08-04):** the
sidecar is written once; any later change is a *superseding* file
(`item-2.json`), never an edit of the original, and the story content
versions with it (`story.txt` → `story-2.txt`). Tests enforce this through
the fake filesystem (`MemoryStore` — fails on any write to an existing
file). The same rule holds for the identity tables: `archive/people.json`
(people + relationships), `places.json`, `themes.json` supersede, never edit
— the derived projection (`app/data`) is regenerated from them by
`loft publish`, so the projection is never hand-edited and never the only
copy (the 2026-08-04 regression: the relationships lived only in the
projection and a merge dropped them).

When the §16.12 hosted store lands, the same contribution endpoint lives there,
the local server is deleted — no shims, clean cutover.

## Sequencing — each slice green (lint + typecheck + tests + browser walk)

| Slice | Ships | Verifiable |
|---|---|---|
| **0 — Data + read side** | story item shape (`date`+`recorded`+`told_by`+verbatim+refs+`comment_on`); "Your memories" block on all four page types; view tests | a seeded story renders attributed on item, person, place, theme pages |
| **1 — AI client + assessment** | localhost contribution endpoint (§16.11 shape); stolen OpenCode client; extraction prompt → proposed links | POST a story → proposed people/places with reasons; tests with injected `urlopen`, no network |
| **2 — The interview** | two-phase protocol; transcript UI; Skip / "That's everything"; progress | a 60-second story → open-ended closure → bounded targeted questions; deterministic prompt tests |
| **3 — Write path + review** | sidecar writes; review screen with redact; verified saves are `catalogued` with `confirmed` refs, abandoned ones `draft` with `proposed` refs | a completed story is verified in the review, saved `catalogued`, and renders on the page |

**Overall acceptance:** on any entity page, tell a 60-second story → open-ended
closure → targeted questions → review (the AI's guesses verified in-flow) →
saved `catalogued` → rendered as an attributed response. A new place named in
the story ("the old ford") enters as `proposed` with a follow-up question,
never a guessed link — and the operator's review confirms or drops it.

## Decisions

**Resolved (2026-08-03):**

- Type: a memory is not a new type — it is an item of type `story` (user).
- Dates (F1): `date` = the events with honest precision; `recorded` = when
  told (user).
- Anchor (F2): branch model — `comment_on` is a string item id; people, places
  and themes link via refs (user).
- Facts (F3): terse facts are verbatim story items; extraction proposes
  entity-field updates that the review confirms or drops (user).
- Write path: same store as the app's info — local archive sidecars now, hosted
  store later (user).
- Identity: alias-resolved against the cast; strangers create `proposed` person
  records (attribution is a Must, §19.2; `proposed` keeps P4).
- Capture kinds: text v1; voice/audio defers to Slice 4's testimony-at-scale.

**Open:**

- AI client env naming (`LOFT_AI_*` vs reusing `find_api_key()`'s
  `OPENCODE_API_KEY`) — settle in Slice 1.
- Keeper-facing confirm surface: the §16.11 import admin view hosts it (assumed);
  revisit when Slice 2 of this plan lands.
