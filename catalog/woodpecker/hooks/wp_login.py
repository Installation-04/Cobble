#!/usr/bin/env python3
"""Headless OAuth login of the service account in Woodpecker; prints its API token (module hook helper).

Woodpecker only hands out user tokens to a browser session, so this script plays the
browser: sign in to the git server, follow the OAuth redirects (rewriting the public
URLs to in-network ones, cookies are kept per host and path-agnostic), then read the
personal token. Standard library only. Credentials come from the environment
(COBBLE_SERVICE_USER, COBBLE_SERVICE_PASSWORD); nothing secret is printed except the token.

Usage: wp_login.py PUBLIC_URL FORGEJO_INTERNAL_URL WOODPECKER_INTERNAL_URL
  e.g. wp_login.py http://nas.local http://forgejo:3000 http://woodpecker-server:8000
"""

from __future__ import annotations

import http.client
import os
import re
import sys
import urllib.parse

MAX_HOPS = 10


class Browser:
    def __init__(self, rewrites: list[tuple[str, str]]) -> None:
        self.rewrites = rewrites
        self.cookies: dict[str, dict[str, str]] = {}

    def _internal(self, url: str) -> str:
        for public, internal in self.rewrites:
            if url.startswith(public):
                return internal + url[len(public) :]
        return url

    def request(
        self,
        method: str,
        url: str,
        form: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], str]:
        parts = urllib.parse.urlsplit(self._internal(url))
        host = parts.netloc
        conn = http.client.HTTPConnection(parts.hostname or "", parts.port or 80, timeout=30)
        headers = {"Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.get(host, {}).items())}
        headers.update(extra_headers or {})
        body = None
        if form is not None:
            body = urllib.parse.urlencode(form)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        conn.request(method, path or "/", body=body, headers=headers)
        resp = conn.getresponse()
        text = resp.read().decode("utf-8", "replace")
        for raw in resp.msg.get_all("Set-Cookie") or []:
            name, _, rest = raw.partition("=")
            value = rest.split(";", 1)[0]
            jar = self.cookies.setdefault(host, {})
            if value in ("", "deleted") or "Max-Age=0" in raw:
                jar.pop(name, None)
            else:
                jar[name] = value
        location = resp.getheader("Location", "")
        if os.environ.get("WP_LOGIN_DEBUG"):
            print(f"{method} {parts.path} -> {resp.status} {location.split('?')[0]}", file=sys.stderr)
        conn.close()
        return resp.status, {"location": location}, text

    def follow(
        self,
        method: str,
        url: str,
        form: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, str]:
        for _ in range(MAX_HOPS):
            status, headers, text = self.request(method, url, form, extra_headers)
            if status not in (301, 302, 303, 307, 308) or not headers["location"]:
                return status, text
            url = urllib.parse.urljoin(url, headers["location"])
            method, form = "GET", None
        raise RuntimeError("too many redirects")


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__, file=sys.stderr)
        return 2
    public, forgejo, woodpecker = (a.rstrip("/") for a in argv[1:4])
    user = os.environ["COBBLE_SERVICE_USER"]
    password = os.environ["COBBLE_SERVICE_PASSWORD"]
    # Forgejo is hosted under /git/ and Woodpecker under /ci/ of the public URL.
    browser = Browser([(f"{public}/git/", f"{forgejo}/"), (f"{public}/ci", f"{woodpecker}/ci")])

    _, page = browser.follow("GET", f"{public}/git/user/login")
    # Older releases carry a CSRF token in the form; recent ones rely on header checks.
    csrf = re.search(r'name="_csrf"\s+value="([^"]+)"', page)
    form = {"user_name": user, "password": password}
    if csrf is not None:
        form["_csrf"] = csrf.group(1)
    status, _, _ = browser.request("POST", f"{public}/git/user/login", form)
    if status != 303:  # a failed sign-in re-renders the form (200)
        print(f"git server sign-in failed (HTTP {status})", file=sys.stderr)
        return 1
    status, page = browser.follow("GET", f"{public}/ci/authorize")
    if 'action="' in page and "/login/oauth/grant" in page:  # consent screen (first login only)
        grant = dict(re.findall(r'<input type="hidden" name="(\w+)" value="([^"]*)"', page))
        grant["granted"] = "true"
        browser.follow("POST", f"{public}/git/login/oauth/grant", grant)
    # Minting a token is a state-changing call: it needs the session's CSRF token.
    _, config = browser.follow("GET", f"{public}/ci/web-config.js")
    csrf_token = re.search(r'WOODPECKER_CSRF = "([^"]+)"', config)
    if csrf_token is None:
        print("cannot find the CI CSRF token; is the sign-in complete?", file=sys.stderr)
        return 1
    status, token = browser.follow(
        "POST", f"{public}/ci/api/user/token", extra_headers={"X-CSRF-TOKEN": csrf_token.group(1)}
    )
    token = token.strip()
    if status != 200 or not re.fullmatch(r"[\w.-]{20,}", token):
        print(f"cannot read the CI token (HTTP {status}); the sign-in did not complete", file=sys.stderr)
        return 1
    print(token)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
