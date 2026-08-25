from app.db.generated.models import User, UserProfile
from app.repositories import ProfileRepository, SkillRepository
from app.schemas.auth import UserOut
from app.schemas.user import MeResponse, ProfileOut, ProfileUpdate, SkillIn, SkillOut


class ProfileService:
    def __init__(self, profiles: ProfileRepository, skills: SkillRepository) -> None:
        self._profiles = profiles
        self._skills = skills

    async def get_me(self, user: User) -> MeResponse:
        profile = await self._profiles.get_by_user_id(user.id)
        return MeResponse(
            user=_user_out(user),
            profile=_profile_out(profile) if profile else None,
            skills=_skills_out(profile),
        )

    async def update_profile(self, user: User, update: ProfileUpdate) -> ProfileOut:
        data = update.model_dump(exclude_unset=True)
        profile = await self._profiles.upsert_for_user(user.id, data)
        return _profile_out(profile)

    async def replace_skills(self, user: User, items: list[SkillIn]) -> list[SkillOut]:
        profile = await self._profiles.get_by_user_id(user.id)
        if profile is None:
            profile = await self._profiles.upsert_for_user(user.id, {})

        # Dedupe by normalized name (last entry wins) before touching the DB.
        deduped: dict[str, SkillIn] = {
            self._skills.normalize(item.skillName): item for item in items
        }
        rows: list[tuple[str, str, float | None]] = []
        for item in deduped.values():
            skill = await self._skills.upsert_by_name(item.skillName.strip())
            rows.append((skill.id, item.proficiency.value, item.yearsOfExperience))
        await self._profiles.replace_skills(profile.id, rows)

        refreshed = await self._profiles.get_by_user_id(user.id)
        return _skills_out(refreshed)


def _user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, name=user.name, createdAt=user.createdAt)


def _profile_out(profile: UserProfile) -> ProfileOut:
    return ProfileOut(
        phone=profile.phone,
        currentRole=profile.currentRole,
        yearsOfExperience=profile.yearsOfExperience,
        targetRoles=profile.targetRoles,
        preferredLocations=profile.preferredLocations,
        remotePreference=profile.remotePreference,
        minimumSalary=profile.minimumSalary,
        preferredSalary=profile.preferredSalary,
        salaryCurrency=profile.salaryCurrency,
        noticePeriodDays=profile.noticePeriodDays,
        education=profile.education,
        industries=profile.industries,
        preferredCompanies=profile.preferredCompanies,
        excludedCompanies=profile.excludedCompanies,
        emailEnabled=profile.emailEnabled,
        telegramEnabled=profile.telegramEnabled,
        telegramChatId=profile.telegramChatId,
        dailyDigestEnabled=profile.dailyDigestEnabled,
        digestMinScore=profile.digestMinScore,
        digestMaxJobs=profile.digestMaxJobs,
        digestTime=profile.digestTime,
    )


def _skills_out(profile: UserProfile | None) -> list[SkillOut]:
    if profile is None or not profile.skills:
        return []
    return [
        SkillOut(
            skillName=user_skill.skill.name if user_skill.skill else "",
            proficiency=user_skill.proficiency,
            yearsOfExperience=user_skill.yearsOfExperience,
        )
        for user_skill in profile.skills
    ]
