import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import RedisDep, SessionDep

router = APIRouter(prefix="/health", tags=["health"])
logger = structlog.get_logger(__name__)


@router.get("/live", summary="Liveness probe")
async def live() -> dict[str, str]:
    """The process is up and serving requests. Checks no dependencies, so a database
    outage does not make an orchestrator restart healthy API containers."""
    return {"status": "ok"}


@router.get(
    "/ready",
    summary="Readiness probe",
    responses={503: {"description": "One or more dependencies are unavailable."}},
)
async def ready(session: SessionDep, redis: RedisDep) -> JSONResponse:
    """The service can do useful work: the database (and Redis, if enabled) respond."""
    checks: dict[str, str] = {}

    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        logger.warning("readiness_check_failed", dependency="database", exc_info=True)
        checks["database"] = "unavailable"

    if redis is not None:
        try:
            await redis.ping()
            checks["redis"] = "ok"
        except Exception:
            logger.warning("readiness_check_failed", dependency="redis", exc_info=True)
            checks["redis"] = "unavailable"

    healthy = all(value == "ok" for value in checks.values())
    return JSONResponse(
        {"status": "ok" if healthy else "unavailable", "checks": checks},
        status_code=200 if healthy else 503,
    )
