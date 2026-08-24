"""LinkedIn — DISABLED.

LinkedIn offers no public job-search API: the Talent Solutions APIs are
partner-gated, and the User Agreement (§8.2) explicitly prohibits scraping or
automated access outside approved integrations. Search results are also
login-walled and bot-protected, which this project never circumvents.

TODO: revisit only if enrolled in the LinkedIn Talent Solutions partner
program; the connector would then use the official partner API with OAuth.
"""

from app.sources.connectors.disabled import DisabledConnector


class LinkedInConnector(DisabledConnector):
    reason = "LinkedIn prohibits scraping; job APIs are partner-only (Talent Solutions)"
