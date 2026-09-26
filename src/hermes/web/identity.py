"""Who is using the app, so each person gets their own library.

Identity comes from Tailscale: `tailscale serve` adds Tailscale-User-Login / -Name headers
naming the signed-in person on every request it forwards. Those headers are only trusted on
connections from this Mac itself (where tailscale serve connects from), because anyone who could
reach the app directly could type them. Everything else (a browser on this Mac, or phones in
--phone mode) is treated as the Mac's owner.
"""

from __future__ import annotations

import functools
import json
import shutil
import subprocess
from dataclasses import dataclass

LOCAL_CLIENTS = {"127.0.0.1", "::1", "localhost"}
TAILSCALE = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"


@dataclass(frozen=True)
class User:
    login: str
    name: str
    is_owner: bool

    @property
    def first_name(self) -> str:
        return self.name.split()[0] if self.name else self.login.split("@")[0]


@functools.lru_cache(maxsize=1)
def owner() -> User:
    """The person signed in to Tailscale on this Mac (or a generic owner without Tailscale)."""
    exe = shutil.which("tailscale") or TAILSCALE
    try:
        status = json.loads(subprocess.run([exe, "status", "--json"], capture_output=True, text=True,
                                           timeout=5).stdout)
        me = (status.get("User") or {}).get(str((status.get("Self") or {}).get("UserID")), {})
        if me.get("LoginName"):
            return User(me["LoginName"].lower(), me.get("DisplayName", ""), True)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return User("owner", "", True)


GUEST = User("guest", "Guest", False)


def current_user(client_host: str | None, headers) -> User:
    if client_host not in LOCAL_CLIENTS:
        return owner()  # --phone mode on a trusted Wi-Fi: single-person
    login, name = headers.get("tailscale-user-login"), headers.get("tailscale-user-name", "")
    forwarded = headers.get("x-forwarded-for", "").split(",")[0].strip()
    if not login and forwarded:
        # Came through tailscale serve without identity headers (e.g. from a shared-in user):
        # ask Tailscale who owns the device at that address. Never fall back to the owner.
        login, name = whois(forwarded)
        if not login:
            return GUEST
    if not login:
        return owner()  # a browser on this Mac itself
    login = login.strip().lower()
    me = owner()
    return me if login == me.login else User(login, name.strip(), False)


@functools.lru_cache(maxsize=256)
def whois(ip: str) -> tuple[str | None, str]:
    exe = shutil.which("tailscale") or TAILSCALE
    try:
        info = json.loads(subprocess.run([exe, "whois", "--json", ip], capture_output=True, text=True,
                                         timeout=5).stdout)
        profile = info.get("UserProfile") or {}
        return profile.get("LoginName"), profile.get("DisplayName", "")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None, ""
