"""Database access layer: all Prisma queries live in repositories so services
stay persistence-agnostic. Inject via the factories in ``app.api.deps``."""

from app.repositories.application_draft_repository import ApplicationDraftRepository
from app.repositories.application_repository import ApplicationRepository
from app.repositories.base import BaseRepository
from app.repositories.company_repository import CompanyRepository
from app.repositories.company_watchlist_repository import CompanyWatchlistRepository
from app.repositories.job_analysis_repository import JobAnalysisRepository
from app.repositories.job_match_repository import JobMatchRepository
from app.repositories.job_repository import JobRepository
from app.repositories.job_source_listing_repository import JobSourceListingRepository
from app.repositories.job_source_repository import JobSourceRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.profile_repository import ProfileRepository
from app.repositories.resume_analysis_repository import ResumeAnalysisRepository
from app.repositories.resume_gap_repository import ResumeGapRepository
from app.repositories.resume_repository import ResumeRepository
from app.repositories.saved_job_repository import SavedJobRepository
from app.repositories.search_run_repository import SearchRunRepository
from app.repositories.skill_repository import SkillRepository
from app.repositories.user_repository import UserRepository

__all__ = [
    "ApplicationDraftRepository",
    "ApplicationRepository",
    "BaseRepository",
    "CompanyRepository",
    "CompanyWatchlistRepository",
    "JobAnalysisRepository",
    "JobMatchRepository",
    "JobRepository",
    "JobSourceListingRepository",
    "JobSourceRepository",
    "NotificationRepository",
    "ProfileRepository",
    "ResumeAnalysisRepository",
    "ResumeGapRepository",
    "ResumeRepository",
    "SavedJobRepository",
    "SearchRunRepository",
    "SkillRepository",
    "UserRepository",
]
