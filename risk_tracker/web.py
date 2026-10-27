"""Build a password-protected, phone-friendly static web page from the report.

The report HTML (with charts embedded) is encrypted with AES-256-GCM using a
key derived from your password (PBKDF2-SHA256). The published page holds only
ciphertext; your browser decrypts it locally with the Web Crypto API after you
type the password. So the page can sit on a free public host such as GitHub
Pages without exposing your positions -- as long as the password is strong.
"""

from __future__ import annotations

import base64
import html
import json
import os
from pathlib import Path

import markdown as md_lib

from . import DISCLAIMER

PBKDF2_ITERATIONS = 600_000


def png_data_uri(path: str | Path) -> str:
    return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode()


def markdown_to_html(text: str) -> str:
    return md_lib.markdown(text, extensions=["tables", "sane_lists"])


def encrypt(plaintext: str, password: str, iterations: int = PBKDF2_ITERATIONS) -> dict:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(hashes.SHA256(), 32, salt, iterations).derive(password.encode())
    ct = AESGCM(key).encrypt(iv, plaintext.encode(), None)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iter": iterations, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)}


def decrypt(payload: dict, password: str) -> str:
    """Python mirror of the in-browser decryption (used by tests)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    d = lambda k: base64.b64decode(payload[k])  # noqa: E731
    key = PBKDF2HMAC(hashes.SHA256(), 32, d("salt"), payload["iter"]).derive(password.encode())
    return AESGCM(key).decrypt(d("iv"), d("ct"), None).decode()


def _icon_png(path: Path, size: int) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(1, 1), dpi=size)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.patch.set_facecolor("#1f5fae")
    ax.fill_between([0.18, 0.82], [0.30, 0.30], [0.62, 0.62], color="#ffffff", alpha=0.22, linewidth=0)
    ax.plot([0.18, 0.34, 0.48, 0.62, 0.82], [0.40, 0.55, 0.44, 0.58, 0.50], color="white",
            linewidth=size / 28, solid_capstyle="round", solid_joinstyle="round")
    fig.savefig(path, dpi=size, facecolor=fig.get_facecolor())
    plt.close(fig)


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Risk Tracker">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="theme-color" content="#f7f7f5" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#161615" media="(prefers-color-scheme: dark)">
<link rel="manifest" href="manifest.webmanifest">
<link rel="apple-touch-icon" href="icon-180.png">
<link rel="icon" href="icon-180.png">
<title>Risk Tracker</title>
<style>
:root {
  --bg: #f7f7f5; --card: #ffffff; --ink: #141413; --ink-2: #5a5954; --line: #e3e2dd;
  --accent: #1f5fae; --warn-bg: #fff4e0; --warn-ink: #7a4b00; --err: #b3261e;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #161615; --card: #1f1f1e; --ink: #f0efec; --ink-2: #b4b3ab; --line: #34332f;
    --accent: #7fb0ee; --warn-bg: #3a2c12; --warn-ink: #f3cf8c; --err: #ff8a80;
  }
}
:root[data-theme="dark"] {
  --bg: #161615; --card: #1f1f1e; --ink: #f0efec; --ink-2: #b4b3ab; --line: #34332f;
  --accent: #7fb0ee; --warn-bg: #3a2c12; --warn-ink: #f3cf8c; --err: #ff8a80;
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  padding: env(safe-area-inset-top) 16px calc(24px + env(safe-area-inset-bottom));
}
main { max-width: 760px; margin: 0 auto; }
header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 0 6px; }
header h1 { font-size: 20px; margin: 0; }
header button { font: inherit; font-size: 14px; color: var(--accent); background: none; border: 0; padding: 8px 0; }
.stamp { color: var(--ink-2); font-size: 14px; margin: 0 0 12px; }
#lock { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 20px; margin-top: 12px; }
#lock p { margin-top: 0; color: var(--ink-2); }
#lock input[type=password] {
  width: 100%; font: inherit; font-size: 17px; padding: 12px; border-radius: 10px;
  border: 1px solid var(--line); background: var(--bg); color: var(--ink);
}
#lock label { display: flex; gap: 8px; align-items: center; margin: 12px 0; color: var(--ink-2); font-size: 15px; }
#lock button.primary {
  width: 100%; font: inherit; font-weight: 600; padding: 12px; border-radius: 10px; border: 0;
  background: var(--accent); color: var(--bg);
}
#err { color: var(--err); min-height: 1.5em; margin: 8px 0 0; font-size: 15px; }
#report h1 { display: none; }
#report h2 { font-size: 19px; margin: 28px 0 8px; padding-top: 16px; border-top: 1px solid var(--line); }
#report h2:first-of-type { border-top: 0; padding-top: 0; }
#report blockquote { margin: 12px 0; padding: 10px 14px; background: var(--warn-bg); color: var(--warn-ink); border-radius: 10px; }
#report blockquote p { margin: 0; }
#report ul { padding-left: 20px; }
#report li { margin: 6px 0; }
#report img { width: 100%; height: auto; border-radius: 10px; border: 1px solid var(--line); background: #fcfcfb; margin: 8px 0; }
#report table { display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; border-collapse: collapse; font-size: 14px; margin: 10px 0; max-width: 100%; }
#report th, #report td { border-bottom: 1px solid var(--line); padding: 6px 10px; text-align: left; white-space: nowrap; vertical-align: top; }
#report th { color: var(--ink-2); font-weight: 600; }
#report hr { border: 0; border-top: 1px solid var(--line); margin: 28px 0 12px; }
footer { color: var(--ink-2); font-size: 13px; margin-top: 24px; }
[hidden] { display: none !important; }
</style>
</head>
<body>
<main>
<header>
  <h1>Risk Tracker</h1>
  <button id="forget" type="button" hidden>Lock</button>
</header>
<p class="stamp">__STAMP__</p>
<section id="lock" __LOCK_HIDDEN__>
  <p>This page is encrypted. Enter your password to unlock it on this device.</p>
  <form id="unlock">
    <input id="pw" type="password" autocomplete="current-password" placeholder="Password" required>
    <label><input id="remember" type="checkbox"> Remember on this device</label>
    <button class="primary" type="submit">Unlock</button>
    <p id="err" role="alert"></p>
  </form>
</section>
<article id="report">__PLAIN__</article>
<footer>__DISCLAIMER__</footer>
</main>
<script>
const PAYLOAD = __PAYLOAD__;
const KEY = "risk-tracker-password";
const store = {
  get() { try { return localStorage.getItem(KEY); } catch (e) { return null; } },
  set(v) { try { localStorage.setItem(KEY, v); } catch (e) {} },
  clear() { try { localStorage.removeItem(KEY); } catch (e) {} },
};
const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
async function decrypt(password) {
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"]);
  const key = await crypto.subtle.deriveKey(
    { name: "PBKDF2", salt: b64(PAYLOAD.salt), iterations: PAYLOAD.iter, hash: "SHA-256" },
    base, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
  const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(PAYLOAD.iv) }, key, b64(PAYLOAD.ct));
  return new TextDecoder().decode(plain);
}
async function unlock(password, remember) {
  const err = document.getElementById("err");
  err.textContent = "Unlocking...";
  try {
    document.getElementById("report").innerHTML = await decrypt(password);
    document.getElementById("lock").hidden = true;
    document.getElementById("forget").hidden = false;
    err.textContent = "";
    if (remember) store.set(password);
  } catch (e) {
    err.textContent = "That password didn't work.";
    store.clear();
  }
}
if (PAYLOAD) {
  document.getElementById("unlock").addEventListener("submit", (e) => {
    e.preventDefault();
    unlock(document.getElementById("pw").value, document.getElementById("remember").checked);
  });
  document.getElementById("forget").addEventListener("click", () => {
    store.clear();
    document.getElementById("report").innerHTML = "";
    document.getElementById("pw").value = "";
    document.getElementById("lock").hidden = false;
    document.getElementById("forget").hidden = true;
  });
  const saved = store.get();
  if (saved) unlock(saved, true);
}
</script>
</body>
</html>
"""


def build_site(report_markdown: str, out_dir: str | Path, password: str | None, stamp: str) -> Path:
    """Write index.html, manifest and icons into ``out_dir``. ``password=None`` publishes in plain text."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    body = markdown_to_html(report_markdown)
    if password:
        payload = json.dumps(encrypt(body, password))
        plain, lock_hidden = "", ""
    else:
        payload, plain, lock_hidden = "null", body, "hidden"
    page = (PAGE.replace("__PAYLOAD__", payload)
                .replace("__PLAIN__", plain)
                .replace("__LOCK_HIDDEN__", lock_hidden)
                .replace("__STAMP__", html.escape(stamp))
                .replace("__DISCLAIMER__", html.escape(DISCLAIMER)))
    (out / "index.html").write_text(page, encoding="utf-8")
    manifest = {
        "name": "Risk Tracker", "short_name": "Risk Tracker", "start_url": "./", "scope": "./",
        "display": "standalone", "background_color": "#f7f7f5", "theme_color": "#1f5fae",
        "icons": [{"src": "icon-180.png", "sizes": "180x180", "type": "image/png"},
                  {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"}],
    }
    (out / "manifest.webmanifest").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for size in (180, 512):
        _icon_png(out / f"icon-{size}.png", size)
    (out / ".nojekyll").write_text("")
    (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    return out / "index.html"
