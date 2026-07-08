from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ActivityLog, User
from app.schemas import ActivityOut
from app.security import get_current_user

router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("", response_model=list[ActivityOut])
def list_activity(limit: int = 50, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(limit).all()
