from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ActivityLog, User
from app.schemas import DBCheckResult, DBCleanResult
from app.security import require_admin
from app.services.db_maintenance import clean_database, scan_database

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])


@router.get("/db-check", response_model=DBCheckResult)
def db_check(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    issues = scan_database(db)
    return DBCheckResult(issues=issues, count=len(issues))


@router.post("/db-clean", response_model=DBCleanResult)
def db_clean(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    issues = scan_database(db)
    result = clean_database(db, issues)
    db.add(ActivityLog(user_id=user.id, action="db_clean", entity="maintenance", payload=result))
    db.commit()
    return DBCleanResult(**result)
