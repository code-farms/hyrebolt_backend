"""Y Combinator / Work at a Startup — DISABLED.

Work at a Startup requires a signed-in account to browse and apply; there is
no public API. This project never automates behind a login wall.

NOTE: many YC companies publish jobs on their own career pages via Greenhouse
or Lever — those are reachable legitimately through the company_careers
connector instead.

TODO: revisit if YC ships a public jobs API/feed.
"""

from app.sources.connectors.disabled import DisabledConnector


class YCombinatorConnector(DisabledConnector):
    reason = "Work at a Startup is login-gated; no public API (use company_careers for YC companies)"
