from fastapi import APIRouter

from app.api.deps import CurrentUserDep, ProfileServiceDep
from app.schemas.user import MeResponse, ProfileOut, ProfileUpdate, SkillOut, SkillsUpdate

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("/me", response_model=MeResponse)
async def get_me(user: CurrentUserDep, profiles: ProfileServiceDep) -> MeResponse:
    return await profiles.get_me(user)


@router.put("/me/profile", response_model=ProfileOut)
async def update_profile(
    payload: ProfileUpdate, user: CurrentUserDep, profiles: ProfileServiceDep
) -> ProfileOut:
    return await profiles.update_profile(user, payload)


@router.put("/me/skills", response_model=list[SkillOut])
async def replace_skills(
    payload: SkillsUpdate, user: CurrentUserDep, profiles: ProfileServiceDep
) -> list[SkillOut]:
    return await profiles.replace_skills(user, payload.skills)
