from fastapi import APIRouter, Request, Response, status

from app.api.dependencies import CurrentUser, SessionDep
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse, UserResponse
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, session: SessionDep):
    _, tokens = await AuthService(session).register(str(payload.email), payload.password)
    return tokens


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, request: Request, session: SessionDep):
    client_ip = request.client.host if request.client else None
    _, tokens = await AuthService(session).login(str(payload.email), payload.password, client_ip)
    return tokens


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, session: SessionDep):
    return await AuthService(session).refresh(payload.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: RefreshRequest, user: CurrentUser, session: SessionDep):
    await AuthService(session).revoke_refresh_token(payload.refresh_token, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser):
    return user
