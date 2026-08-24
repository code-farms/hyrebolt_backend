"""Foundit (formerly Monster India) — DISABLED.

Foundit exposes no public job-search API; programmatic access is limited to
paid recruiter products and the site is bot-protected.

TODO: revisit if Foundit publishes a public API or partner feed.
"""

from app.sources.connectors.disabled import DisabledConnector


class FounditConnector(DisabledConnector):
    reason = "no public API; recruiter products only"
