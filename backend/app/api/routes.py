from fastapi import APIRouter

router = APIRouter()


@router.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """Report API process liveness. Database readiness is added with persistence."""
    return {"status": "ok"}
