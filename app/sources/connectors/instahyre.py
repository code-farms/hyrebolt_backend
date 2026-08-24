"""Instahyre — DISABLED.

Instahyre is an invite/login-gated matching platform with no public API or
feed.

TODO: revisit if an official API appears.
"""

from app.sources.connectors.disabled import DisabledConnector


class InstahyreConnector(DisabledConnector):
    reason = "login-gated platform; no public API"
