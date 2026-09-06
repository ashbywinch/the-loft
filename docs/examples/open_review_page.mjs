// Open a Loft review page with a valid session and screenshot it.
//
// `cookie` is the output of examples/make_review_cookie.py; `url` is the
// review URL (see docs/review-surface.md for the format). With the harness
// browser: await tab.run(code, { args: [{ cookie, url }] })
// Use page.setCookie — NEVER document.cookie: the harness `run` action
// executes in Node, not the page DOM. The cookie is scoped to `url` (no
// domain attribute — cookie domains never carry ports), so it applies
// whatever host the page is opened on: localhost, 127.0.0.1, or the LAN
// address make serve prints.
async ({ page }, { cookie, url }) => {
  await page.setCookie({ name: "session", value: cookie, url });
  await page.goto(url, { waitUntil: "networkidle2" });
  await page.screenshot({ path: "review-page.png", fullPage: true });
};
