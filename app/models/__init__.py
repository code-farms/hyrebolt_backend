"""Domain vocabulary for the app.

The Prisma-generated types under ``app.db.generated`` are the domain models;
this package re-exports the schema enums so app code imports them from a
stable location instead of reaching into the generated client.
"""

from app.db.generated.enums import (
    ApplicationStatus,
    EmploymentType,
    MatchFeedback,
    MatchRecommendation,
    NotificationChannel,
    NotificationStatus,
    NotificationType,
    RemotePreference,
    SearchRunStatus,
    SearchTrigger,
    SkillProficiency,
    WatchlistPriority,
)

__all__ = [
    "ApplicationStatus",
    "EmploymentType",
    "MatchFeedback",
    "MatchRecommendation",
    "NotificationChannel",
    "NotificationStatus",
    "NotificationType",
    "RemotePreference",
    "SearchRunStatus",
    "SearchTrigger",
    "SkillProficiency",
    "WatchlistPriority",
]
