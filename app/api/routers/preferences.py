from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUserDep, PreferenceSignalServiceDep
from app.core.exceptions import NotFoundError
from app.schemas.preferences import LearnedPreferencesOut, learned_preferences_out

router = APIRouter(prefix="/api/v1/preferences", tags=["preferences"])


@router.get("", response_model=LearnedPreferencesOut)
async def get_preferences(
    user: CurrentUserDep, signals: PreferenceSignalServiceDep
) -> LearnedPreferencesOut:
    return learned_preferences_out(await signals.learn(user))


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def reset_preferences(user: CurrentUserDep, signals: PreferenceSignalServiceDep) -> Response:
    """Forget everything learned. Feedback flags, saved jobs and applications
    are untouched — only the learning signals go."""
    await signals.reset(user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/signals/{signal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_signal(
    signal_id: str, user: CurrentUserDep, signals: PreferenceSignalServiceDep
) -> Response:
    if not await signals.remove_signal(user, signal_id):
        raise NotFoundError("Signal not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
