"""DailyDigestService (Phase 10).

Builds the spec digest (Good Morning + 🔥/🟢/🟡 bands, per-job details) and
delivers it per channel:
- IN_APP: always created (bell) — no external send, cannot be disabled.
- EMAIL / TELEGRAM: only when the provider is env-configured AND the user has
  the channel + dailyDigest enabled. One Notification row per channel with a
  unique dedupeKey — SENT rows are never re-sent; FAILED rows retry next run.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.core.logging import get_logger
from app.db.generated.models import JobMatch, User, UserProfile
from app.models import NotificationChannel, NotificationStatus, NotificationType
from app.notifications import NotificationProvider, NotificationSendError
from app.repositories import NotificationRepository, ProfileRepository
from app.services.ranking_service import RankingService

logger = get_logger(__name__)

FIRE_THRESHOLD = 85.0
STRONG_THRESHOLD = 70.0

_BAND_TITLES = {
    "excellent": "🔥 Excellent Matches",
    "strong": "🟢 Strong Matches",
    "potential": "🟡 Potential Matches",
}


@dataclass
class DigestItem:
    jobId: str
    company: str | None
    title: str | None
    location: str | None
    salary: str | None
    score: float
    whyMatch: str | None
    missingSkills: list[str]
    source: str | None
    applyUrl: str | None
    band: str


@dataclass
class DigestContent:
    date: str
    subject: str
    body: str
    items: list[DigestItem] = field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "items": [vars(item) for item in self.items],
        }


def _band(score: float) -> str:
    if score >= FIRE_THRESHOLD:
        return "excellent"
    if score >= STRONG_THRESHOLD:
        return "strong"
    return "potential"


def _salary_text(job: Any) -> str | None:
    if job is None or (job.salaryMin is None and job.salaryMax is None):
        return None
    low = f"{job.salaryMin:,}" if job.salaryMin is not None else "?"
    high = f"{job.salaryMax:,}" if job.salaryMax is not None else "?"
    currency = job.salaryCurrency or ""
    return f"{currency} {low}–{high}".strip()


def _primary_listing(job: Any) -> Any | None:
    listings = getattr(job, "listings", None) or []
    primary = next((entry for entry in listings if entry.isPrimary), None)
    return primary or (listings[0] if listings else None)


class DailyDigestService:
    def __init__(
        self,
        ranking: RankingService,
        profiles: ProfileRepository,
        notifications: NotificationRepository,
        providers: dict[NotificationChannel, NotificationProvider],
    ) -> None:
        self._ranking = ranking
        self._profiles = profiles
        self._notifications = notifications
        self._providers = providers

    async def build_digest(
        self, user: User, profile: UserProfile, run_date: date
    ) -> DigestContent | None:
        rows, _ = await self._ranking.recommended(
            user,
            limit=max(1, profile.digestMaxJobs),
            offset=0,
            min_score=float(profile.digestMinScore),
        )
        if not rows:
            return None
        items = [self._item_from_match(row) for row in rows]
        date_str = run_date.isoformat()
        return DigestContent(
            date=date_str,
            subject=f"Your daily job digest — {len(items)} matches ({date_str})",
            body=self._render_body(items),
            items=items,
        )

    async def send_for_user(self, user: User, run_date: date) -> dict[str, str]:
        """Returns {channel: outcome} where outcome is created/sent/skipped/
        failed/deduped."""
        profile = await self._profiles.get_by_user_id(user.id)
        if profile is None or not profile.dailyDigestEnabled:
            return {}
        digest = await self.build_digest(user, profile, run_date)
        if digest is None:
            return {}

        outcomes: dict[str, str] = {}

        # In-app: always. No external delivery step — the row IS the delivery.
        _, created = await self._create_row(
            user, digest, NotificationChannel.IN_APP, run_date
        )
        outcomes["in_app"] = "created" if created else "deduped"

        if profile.emailEnabled and NotificationChannel.EMAIL in self._providers:
            outcomes["email"] = await self._deliver(
                user, profile, digest, NotificationChannel.EMAIL, run_date
            )
        if profile.telegramEnabled and NotificationChannel.TELEGRAM in self._providers:
            outcomes["telegram"] = await self._deliver(
                user, profile, digest, NotificationChannel.TELEGRAM, run_date
            )
        return outcomes

    async def _deliver(
        self,
        user: User,
        profile: UserProfile,
        digest: DigestContent,
        channel: NotificationChannel,
        run_date: date,
    ) -> str:
        row, created = await self._create_row(user, digest, channel, run_date)
        if not created and row.status == NotificationStatus.SENT:
            return "deduped"  # never send the same digest twice
        provider = self._providers[channel]
        try:
            await provider.send(row, user, profile)
        except NotificationSendError as exc:
            await self._notifications.mark_failed(row.id, exc.message)
            logger.warning(
                "notification_send_failed",
                channel=str(channel),
                user_id=user.id,
                error=exc.message,
            )
            return "failed"
        await self._notifications.mark_sent(row.id)
        logger.info("notification_sent", channel=str(channel), user_id=user.id)
        return "sent"

    async def _create_row(
        self,
        user: User,
        digest: DigestContent,
        channel: NotificationChannel,
        run_date: date,
    ):
        return await self._notifications.create_if_absent(
            dedupe_key=f"digest:{user.id}:{run_date.isoformat()}:{channel.lower()}",
            user_id=user.id,
            channel=channel,
            notification_type=NotificationType.DAILY_DIGEST,
            subject=digest.subject,
            body=digest.body,
            payload=digest.payload(),
        )

    def _item_from_match(self, match: JobMatch) -> DigestItem:
        job = match.job
        listing = _primary_listing(job)
        source = None
        apply_url = None
        if listing is not None:
            source = listing.source.displayName if listing.source else None
            apply_url = listing.sourceUrl or listing.canonicalUrl
        if apply_url is None and job is not None:
            apply_url = job.sourceUrl or job.canonicalUrl
        return DigestItem(
            jobId=match.jobId,
            company=job.companyName if job else None,
            title=job.title if job else None,
            location=job.location if job else None,
            salary=_salary_text(job),
            score=match.overallScore,
            whyMatch=match.whyMatch,
            missingSkills=list(match.missingSkills or []),
            source=source,
            applyUrl=apply_url,
            band=_band(match.overallScore),
        )

    def _render_body(self, items: list[DigestItem]) -> str:
        lines = ["Good Morning!", ""]
        for band in ("excellent", "strong", "potential"):
            band_items = [item for item in items if item.band == band]
            if not band_items:
                continue
            lines.append(_BAND_TITLES[band])
            for item in band_items:
                lines.append(f"• {item.title} @ {item.company} — score {item.score}")
                details = []
                if item.location:
                    details.append(item.location)
                if item.salary:
                    details.append(item.salary)
                if item.source:
                    details.append(f"via {item.source}")
                if details:
                    lines.append(f"  {' | '.join(details)}")
                if item.whyMatch:
                    lines.append(f"  Why: {item.whyMatch}")
                if item.missingSkills:
                    lines.append(f"  Missing: {', '.join(item.missingSkills)}")
                if item.applyUrl:
                    lines.append(f"  Apply: {item.applyUrl}")
            lines.append("")
        return "\n".join(lines).strip()
