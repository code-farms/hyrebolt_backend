"""Career-board helpers for the company_careers connector (Phase 13).

A watchlisted company's careers URL may point at a Greenhouse or Lever public
board — the two providers with read-only JSON APIs published for third-party
rendering. Only those hosts derive a board; any other URL is kept as plain
metadata and never fetched, so nothing here can widen the crawl surface
beyond what docs/job-sources.md permits."""

import re
from urllib.parse import parse_qs, urlsplit

GREENHOUSE_PUBLIC_BOARD = "https://boards.greenhouse.io/{token}"
LEVER_PUBLIC_BOARD = "https://jobs.lever.co/{token}"

_GREENHOUSE_HOSTS = {"boards.greenhouse.io", "job-boards.greenhouse.io"}
_LEVER_HOSTS = {"jobs.lever.co", "jobs.eu.lever.co"}
# The token is interpolated into the upstream API path; anything outside a
# board slug (e.g. "..") must never reach the request URL.
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def public_board_url(provider: str, token: str) -> str | None:
    if provider == "greenhouse":
        return GREENHOUSE_PUBLIC_BOARD.format(token=token)
    if provider == "lever":
        return LEVER_PUBLIC_BOARD.format(token=token)
    return None


def board_from_careers_url(company: str, url: str | None) -> dict[str, str] | None:
    """Returns a company_careers board config `{company, provider, token}` when
    `url` is a recognised Greenhouse/Lever public board, else None."""
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    host = parts.hostname.casefold() if parts.hostname else ""
    segments = [segment for segment in parts.path.split("/") if segment]

    token: str | None = None
    provider: str | None = None
    if host in _GREENHOUSE_HOSTS:
        provider = "greenhouse"
        if segments[:2] == ["embed", "job_board"]:
            token = (parse_qs(parts.query).get("for") or [None])[0]
        elif segments:
            token = segments[0]
    elif host in _LEVER_HOSTS:
        provider = "lever"
        if segments:
            token = segments[0]

    if provider is None or not token or not _TOKEN_RE.match(token):
        return None
    return {"company": company.strip(), "provider": provider, "token": token}


def merge_boards(
    base: list[dict[str, str]], extra: list[dict[str, str]]
) -> list[dict[str, str]]:
    """Dedupe by (provider, token); operator-configured boards win."""
    merged: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for board in [*base, *extra]:
        key = (board.get("provider", ""), board.get("token", "").casefold())
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        merged.append(board)
    return merged
