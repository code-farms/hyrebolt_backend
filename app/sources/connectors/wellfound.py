"""Wellfound (AngelList Talent) — DISABLED.

Wellfound's API is limited to ATS/recruiting partners; public job browsing is
heavily bot-protected and the ToS prohibit scraping.

TODO: revisit via the official partner API if access is granted; startup
metadata (Phase 13) would come from the same integration.
"""

from app.sources.connectors.disabled import DisabledConnector


class WellfoundConnector(DisabledConnector):
    reason = "API is partner-only; ToS prohibit scraping"
