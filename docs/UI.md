# UI Pattern Library — tokens and components

- **Status:** guidelines (2026-08-03). The one way to style the app: components
  reference semantic tokens only, and new UI goes through the classes below —
  a new component style requires updating this library (the design-system
  counterpart of the archive library, docs/CHAT-UX.md, docs/MEMORIES.md).
- **Research basis:** primitive → semantic → component tokens; every
  hard-coded value in component CSS is a gap; a pattern library is the
  enforcement point for a vanilla app.

## Tokens (`:root` in styles.css)

Semantic tokens only — components never hard-code values:

| Token | Meaning |
|---|---|
| `--bg`, `--card`, `--paper` | surfaces: page / raised / inset-input |
| `--ink`, `--muted` | text: primary / secondary |
| `--line` | borders and dividers |
| `--accent`, `--accent-soft` | the action colour and its wash |
| `--on-accent` | text on the accent fill (never raw `#fff`) |
| `--shadow` | the one elevation |
| `--r-sm/md/lg/xl` | radii — components pick one, never a literal |
| `--control-h` | the 44px touch-target height |
| `--gap-sm/gap/gap-lg` | the spacing scale |

## Components

| Class | Use | Notes |
|---|---|---|
| `.btn` | any button | 44px target, pill, quiet (card bg) |
| `.btn-primary` | the one action that ends/advances the flow | accent fill, `--on-accent` text; with `.btn` |
| `.btn-danger` | a destructive action (abandon a draft) — two taps: ask, then confirm | muted red fill; with `.btn` |
| `.btn:disabled` | while busy | dimmed, cursor default |
| `.field` | inputs, selects, textareas | inset paper surface |
| `.field-textarea` | multi-line fields | with `.field` |
| `.field-sm` | compact fields (inline rows) | with `.field`, width auto |
| `.chip` | small label/link pills | existing |
| `.bubble` / `.bubble-user` / `.bubble-ai` | chat messages | user right (accent wash), assistant left (paper); the header line `.bubble-who` is separate from the body |
| `.card`, `.item-card` | content cards | existing |
| `.memories-note` | the tap's feedback card | accent-bordered, deliberately distinct |
| `.link-toggle` | keep/remove toggles in the review | labelled checkbox, obvious state |

## Rules

1. **Components reference tokens only.** A literal colour, radius, or spacing
   in a component rule is a gap — use the token.
2. **Never invent a parallel button/input/bubble style.** If `.btn` /
   `.field` / `.bubble` don't fit, extend them here — that is the mechanism
   that keeps the app consistent (user, 2026-08-03).
3. **The primary action stands out.** The flow-ending action is
   `.btn-primary`; supporting actions are quiet `.btn`.
4. **Touch targets ≥ 44px**; contrast on the beige palette; respect
   `prefers-reduced-motion`.
5. **Chat surfaces go through `app/chat.js`** (docs/CHAT-UX.md) — the
   components are the styling layer under it.

## Components added by the 2026-08-05/06 rounds (all in styles.css)

- `.period` / `.period-summary` — the timeline's count-sized periods: the
  range (serif, accent), the theme hook (italic serif), the entry count
  (muted, right). The spine reads newest-first both between and within
  periods.
- `.event-card` — a derived life event on the spine ("Harper Pryce · born"):
  card language, serif name + muted verb, links to the person.
- `.card-desc` — the distinguishing description on a card: muted, two-line
  clamp with ellipsis; full text is the item page's lede.
- `.clarification` / `.clarifications` — the fragment/reflection note on the
  pages they attest: paper card, accent left rule, teller in card-meta —
  never a story card.
- `.tree-more` / `.tree-back` — the tree's clues: muted "+N more" for family
  beyond the view; the accent-pill "leads back to you" on the path card.
- `.map-ring` (+ `.map-ring-wide`) — the uncertainty ring for imprecise
  places: translucent fill, soft stroke, sized by precision tier; a pin is
  only ever drawn for a point that IS the place.
