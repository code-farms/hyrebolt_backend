"""Development-only database seed.

Run inside the api container:

    make seed
    # or: docker compose exec api uv run python -m app.db.seed

Idempotent: every write is an upsert on a unique key, so re-running is safe.
Seeds reference data (skills, job sources) and one dev user with a profile.
It deliberately creates NO jobs — job rows only ever come from real discovery.
"""

import asyncio
from typing import NamedTuple

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.client import connect_db, disconnect_db, prisma_client
from app.db.generated.enums import SkillProficiency
from app.repositories import JobSourceRepository, SkillRepository, UserRepository

logger = get_logger(__name__)

DEV_USER_EMAIL = "dev@job-agent.local"
# Conventional "unusable password" marker; Phase 3 introduces real hashing and
# no login is possible until then.
UNUSABLE_PASSWORD_HASH = "!"

# (name, category)
SKILLS: list[tuple[str, str]] = [
    ("Python", "language"),
    ("TypeScript", "language"),
    ("JavaScript", "language"),
    ("SQL", "language"),
    ("Go", "language"),
    ("Java", "language"),
    ("FastAPI", "framework"),
    ("Django", "framework"),
    ("React", "framework"),
    ("Node.js", "framework"),
    ("Next.js", "framework"),
    ("PostgreSQL", "database"),
    ("MySQL", "database"),
    ("MongoDB", "database"),
    ("Redis", "database"),
    ("Docker", "devops"),
    ("Kubernetes", "devops"),
    ("AWS", "cloud"),
    ("GCP", "cloud"),
    ("CI/CD", "devops"),
    ("REST APIs", "concept"),
    ("System Design", "concept"),
]

class SourceSeed(NamedTuple):
    name: str
    display_name: str
    base_url: str | None
    requires_auth: bool
    capabilities: list[str]


# The Phase 4 connector list. All disabled until a connector exists and its
# access method has been verified against the platform's terms.
JOB_SOURCES: list[SourceSeed] = [
    SourceSeed("linkedin", "LinkedIn", "https://www.linkedin.com", True, ["search", "details"]),
    SourceSeed("naukri", "Naukri", "https://www.naukri.com", False, ["search", "details"]),
    SourceSeed("indeed", "Indeed", "https://www.indeed.com", False, ["search", "details"]),
    SourceSeed("cutshort", "Cutshort", "https://cutshort.io", True, ["search"]),
    SourceSeed("wellfound", "Wellfound", "https://wellfound.com", True, ["search", "startup_metadata"]),
    SourceSeed(
        "ycombinator",
        "Y Combinator / Work at a Startup",
        "https://www.workatastartup.com",
        True,
        ["search", "startup_metadata"],
    ),
    SourceSeed("instahyre", "Instahyre", "https://www.instahyre.com", True, ["search"]),
    SourceSeed("foundit", "Foundit", "https://www.foundit.in", False, ["search"]),
    SourceSeed("remoteok", "Remote OK", "https://remoteok.com", False, ["api", "feed"]),
    SourceSeed("weworkremotely", "We Work Remotely", "https://weworkremotely.com", False, ["feed"]),
    SourceSeed("company_careers", "Company career pages", None, False, ["scrape_permitted_pages"]),
]

DEV_PROFILE_SKILLS: list[tuple[str, SkillProficiency, float]] = [
    ("Python", SkillProficiency.ADVANCED, 4.0),
    ("FastAPI", SkillProficiency.ADVANCED, 3.0),
    ("React", SkillProficiency.INTERMEDIATE, 2.0),
    ("PostgreSQL", SkillProficiency.INTERMEDIATE, 3.0),
]


async def seed() -> None:
    settings = get_settings()
    configure_logging(settings)

    if settings.environment == "production":
        raise SystemExit("Refusing to seed: this seed is for development only.")

    await connect_db()
    try:
        skill_repo = SkillRepository(prisma_client)
        source_repo = JobSourceRepository(prisma_client)
        user_repo = UserRepository(prisma_client)

        skill_ids: dict[str, str] = {}
        for name, category in SKILLS:
            skill = await skill_repo.upsert_by_name(name, category=category)
            skill_ids[name] = skill.id
        logger.info("seeded_skills", count=len(SKILLS))

        for source in JOB_SOURCES:
            await source_repo.upsert_by_name(
                source.name,
                display_name=source.display_name,
                base_url=source.base_url,
                requires_auth=source.requires_auth,
                capabilities=source.capabilities,
            )
        logger.info("seeded_job_sources", count=len(JOB_SOURCES))

        user = await user_repo.upsert_by_email(
            DEV_USER_EMAIL, password_hash=UNUSABLE_PASSWORD_HASH, name="Dev User"
        )
        profile = await prisma_client.userprofile.upsert(
            where={"userId": user.id},
            data={
                "create": {
                    "userId": user.id,
                    "currentRole": "Backend Engineer",
                    "yearsOfExperience": 3.0,
                    "targetRoles": ["Backend Engineer", "Full Stack Engineer"],
                    "preferredLocations": ["Bengaluru", "Remote"],
                    "industries": ["SaaS", "Fintech"],
                },
                "update": {},
            },
        )
        for skill_name, proficiency, years in DEV_PROFILE_SKILLS:
            await prisma_client.userskill.upsert(
                where={
                    "profileId_skillId": {
                        "profileId": profile.id,
                        "skillId": skill_ids[skill_name],
                    }
                },
                data={
                    "create": {
                        "profileId": profile.id,
                        "skillId": skill_ids[skill_name],
                        "proficiency": proficiency,
                        "yearsOfExperience": years,
                    },
                    "update": {"proficiency": proficiency, "yearsOfExperience": years},
                },
            )
        logger.info("seeded_dev_user", email=DEV_USER_EMAIL)
    finally:
        await disconnect_db()


if __name__ == "__main__":
    asyncio.run(seed())
