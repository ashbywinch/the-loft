# Chat UX — the capture dialog and any future chat surface

- **Status:** guidelines (2026-08-03). Applies to the story-capture sheet and
  any chat UI the app adds. Backed by `app/chat.js` — new chat functionality
  goes through the library so the layout stays consistent
  (docs/prd/MEMORIES.md). Research basis: mobile chat-app guidance (bottom
  input, left/right bubbles, disabled-while-busy, 44px, contrast); the
  deviations below are the user's explicit product calls.

## The layout

- The chat is a column: **messages → quick replies → input bar**. The
  composer is the bottom-most interactive element; **nothing sits below it**
  (standard guidance, e.g. Ethora's chat patterns, setproduct's AI-chat
  anatomy). An earlier "actions below the input" call is reversed (user,
  2026-08-03): it looked wrong in practice and the guidance is unanimous.
- **Quick replies are chips** (pill buttons, 3–4 max, wrapping) between the
  last message and the composer (BotHero; shadcn; Telerik). Tapping a chip
  "sends" it and the row clears, like any sent reply. "That's everything" is
  such an escape chip — the end-of-turn affordance is a suggestion, never a
  stray full-width button.
- The **input bar docks at the bottom** of the sheet, above the on-screen
  keyboard; only the messages scroll (standard chat-app guidance).
- The **input grows with the message**, capped (200px) so a long account
  scrolls inside the box instead of filling the screen — a story is never
  squeezed into one line.
- **Nothing told is lost — ever.** The whole transcript (who, every message,
  the assessment, where the flow was) auto-saves to the server ~1.5s after
  any change, superseding the same draft id in place (append-only), plus on
  close and unload. A distraction or a server reboot loses at most the last
  few words; Continue on a draft **replays the chat** up to where the
  narrator left it and the flow carries on live (user, 2026-08-03).
- **Send button on the bottom right** — the phone-thumb side (user,
  2026-08-03, correcting an earlier mistaken "left" call; right is the
  standard guidance this app researched and follows).

## Messages

- Assistant messages on the **left**, narrator messages on the **right**, with
  distinct bubble styles (standard guidance).
- The assistant is the app itself ("The Loft"). A bubble header is a small
  label **separated from the body** — never a label concatenated with the
  prompt text.
- The current question stays above the fold; a long transcript must not push
  it off-screen.

## Input

- Placeholder is short and generic; it must **not repeat the assistant's
  prompt** (the prompt is a bubble, the placeholder is guidance for the box).
- The send button is **disabled when the input is empty and whenever the
  assistant is busy** (reading / assessing / saving) — the narrator cannot
  type or send while the assistant is working (user, 2026-08-03).
- Primary actions ("That's everything", "Use this date", "Skip") live in the
  action row below the input, always reachable while not busy.

## Autocomplete

- Name fields autocomplete over the cast (names + aliases) with a **custom
  dropdown that filters as you type** — not a native `<datalist>`, which does
  not work on mobile browsers (user, 2026-08-03). Tap to select; arrow
  keys + Enter as the keyboard fallback.

## States and feedback

- Busy: the assistant's "reading…" message shows, and input + send + actions
  are disabled — with the reason visible in the message stream.
- Every tappable control gives **obvious** pressed/selected feedback — a
  visible state change, not a subtle border (the "tap to drop or keep" chips
  read as static pills without it).
- Touch targets ≥ 44px; contrast sufficient on the beige palette; respect
  `prefers-reduced-motion`.
- **Nothing told is lost:** the sheet saves a draft on close **and on page
  unload** (`beforeunload`), so a reboot never eats an in-progress account.

## The review step

- Say what happens in plain words: "These connections were picked out of
  your story — tick to keep, untick to leave out." The review IS the
  verification of the AI's guesses (user, 2026-08-03) — no later gate.
- Kept links read as kept (checked); removed ones visibly leave the list;
  adding a person or place is one inline row (kind + name + Add).
- The save button says what it does ("Save story") and the outcome is stated
  beneath it ("Saved straight to the archive — your story is live").

## Autocomplete over the cast (the narrator picker)

- A combobox with list autocomplete (W3C APG): type to filter, arrow keys
  navigate, Enter selects — the typed text is never auto-selected, picking
  is explicit. The active option is highlighted; the list is capped at 8 and
  opens upward when the input sits at the bottom of the screen (Baymard:
  manageable list, visible highlight, mobile spacing).
- The chosen name is **committed, not free text**: once sent it renders as a
  **removable pill with an X** — the committed-value chip pattern (GEL,
  eBay MIND chips-combobox: "each selected item becomes a chip with a close
  button", `aria-label="Remove [item]"`). The X is a real button with an
  accessible name, removal is immediate (no confirmation), and it returns to
  the picker without losing the story already told (uxpatterns.dev, Chip
  A11y patterns, Material 3).
- Custom dropdown, never a native datalist — datalists do not work on
  mobile (user, 2026-08-03).
