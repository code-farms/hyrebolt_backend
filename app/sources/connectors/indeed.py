"""Indeed — DISABLED.

Indeed retired its public Publisher (Job Search) API; current APIs are
partner/ATS-gated. Search pages are bot-protected and the ToS prohibit
scraping.

TODO: revisit via the Indeed Partner Platform if partnership is obtained; the
connector would use the official GraphQL API with issued credentials.
"""

from app.sources.connectors.disabled import DisabledConnector


class IndeedConnector(DisabledConnector):
    reason = "publisher API retired; remaining APIs are partner-only"
