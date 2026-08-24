"""Cutshort — DISABLED.

Cutshort has no public job-search API and job browsing is account-gated
beyond a few teaser pages. No permitted feed exists.

TODO: revisit if Cutshort offers an official API/integration; connector would
use issued credentials.
"""

from app.sources.connectors.disabled import DisabledConnector


class CutshortConnector(DisabledConnector):
    reason = "no public API; listings are account-gated"
