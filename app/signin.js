/** The web-flow sign-in (2026-08-06): houses' proven mechanism.

 * The callback host is a registered hostname that resolves to the LAN IP
 * (`192.168.1.251.sslip.io`) — Google accepts hostname redirect URIs, so
 * the standard authorization-code flow works from the phone: redirect to
 * Google, back through the registered callback, the cookie lands on the
 * page navigation. No code entry, no polling — the device flow was the
 * wrong path for a browser (the LAN IP can't be registered and the phone
 * rejects fetch-carried cookies).
 */

export async function signInSheet() {
  // fetch the login endpoint and follow the auth_url it returns — the
  // endpoint answers JSON, so navigating straight to it would render the
  // URL as text (2026-08-06, user: 'I just pasted you exactly what I saw')
  try {
    const res = await fetch("/api/auth/login");
    const data = await res.json();
    if (data.auth_url) {
      location.href = data.auth_url;
    }
  } catch {
    // the server isn't reachable — the gate stays; nothing to show
  }
}
