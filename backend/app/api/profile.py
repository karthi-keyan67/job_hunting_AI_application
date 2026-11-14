from fastapi import APIRouter

from app.api.dependencies import CurrentUser, SessionDep
from app.schemas.preferences import PreferencesResponse, PreferencesUpdate
from app.schemas.profile import ProfileResponse, ProfileUpdate
from app.services.profile import ProfileService

router = APIRouter(tags=["profile"])


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(user: CurrentUser, session: SessionDep):
    return await ProfileService(session).get_profile(user.id)


@router.put("/profile", response_model=ProfileResponse)
async def update_profile(payload: ProfileUpdate, user: CurrentUser, session: SessionDep):
    return await ProfileService(session).update_profile(user.id, payload.model_dump())


@router.get("/preferences", response_model=PreferencesResponse)
async def get_preferences(user: CurrentUser, session: SessionDep):
    return await ProfileService(session).get_preferences(user.id)


@router.put("/preferences", response_model=PreferencesResponse)
async def update_preferences(payload: PreferencesUpdate, user: CurrentUser, session: SessionDep):
    return await ProfileService(session).update_preferences(user.id, payload.model_dump())
