# Review surface — sign in and look at the rendered page

The transcription-review surface (`#/review/<batch_id>/<doc_index>/<page_index>`,
all 0-indexed). Before claiming a layout or geometry change works, open the
app and look at the rendered page with the boxes drawn — unit tests and
evals test data, not the rendered UI.

## Start the server

`make serve` (the loft script sources `.env` and serves on the LAN address
printed; the session secret and review identity come from `.env`).

## Sign in as a test session

The server signs its own session cookies. Create one from the server's
secret and set it in the headless browser — no human login:

1. Source `.env`, then run
   [make_review_cookie.py](examples/make_review_cookie.py) with
   `LOFT_REVIEW_EMAIL` (required) and `LOFT_REVIEW_NAME` (optional) set in
   `.env`. A different secret silently produces an invalid cookie
   (`authenticated: false`, no error).
2. Open the review page with the cookie set —
   [open_review_page.mjs](examples/open_review_page.mjs): `page.setCookie`
   scoped to the target URL (never `document.cookie` — the harness `run`
   action executes in Node, not the page DOM), `waitUntil:
   "networkidle2"`, screenshot.

Example: page-01 of the first document in batch `adopt-20260813-201004` is
`#/review/adopt-20260813-201004/0/0`.

## Inspect the screenshot

- Do the boxes sit on the text?
- Are all lines covered?
- Are margin annotations separate from the text boxes?

## Common mistakes (each cost a full session)

- **Wrong branch**: editing while HEAD is on a different branch than the
  one you think — check `git branch --show-current`.
- **Wrong session secret**: forging the cookie without sourcing `.env`, so
  the serializer uses a different key than the server.
- **Not looking at the render**: reporting "all lines boxed" from the
  layout JSON without checking that the boxes actually sit on the text.
- **Not running the real pipeline on real data**: fixtures in tmp
  directories prove nothing about the family's actual scans.
- **Delegating the visual check to the user**: verify it yourself.
