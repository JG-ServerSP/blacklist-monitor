from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.runtime_settings import effective_settings
from app.security import require_admin
from app.services.logs_reader import read_recent_logs

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("")
def get_logs(
    level: str | None = None,
    q: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    tz_name = effective_settings(db).timezone or "UTC"
    return read_recent_logs(level=level, q=q, limit=min(limit, 1000), tz_name=tz_name)
