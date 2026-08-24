"""Naukri — DISABLED.

Naukri exposes no public job-search API; programmatic access is limited to
paid recruiter/enterprise products, and the site's terms prohibit automated
crawling of listings. No permitted feed exists.

TODO: revisit if Naukri publishes a public API or partner feed; the connector
would authenticate with issued credentials via the official endpoint.
"""

from app.sources.connectors.disabled import DisabledConnector


class NaukriConnector(DisabledConnector):
    reason = "no public API; terms prohibit automated crawling"
