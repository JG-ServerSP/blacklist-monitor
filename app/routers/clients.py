from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Client, User
from app.schemas import ClientCreate, ClientOut
from app.security import get_current_user, require_operator

router = APIRouter(prefix="/api/clients", tags=["clients"])


@router.get("", response_model=list[ClientOut])
def list_clients(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Client).order_by(Client.name).all()


@router.post("", response_model=ClientOut)
def create_client(payload: ClientCreate, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    client = Client(**payload.model_dump())
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


@router.get("/{client_id}", response_model=ClientOut)
def get_client(client_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    client = db.query(Client).get(client_id)
    if not client:
        raise HTTPException(404, "Cliente não encontrado")
    return client


@router.put("/{client_id}", response_model=ClientOut)
def update_client(client_id: int, payload: ClientCreate, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    client = db.query(Client).get(client_id)
    if not client:
        raise HTTPException(404, "Cliente não encontrado")
    for k, v in payload.model_dump().items():
        setattr(client, k, v)
    db.commit()
    db.refresh(client)
    return client


@router.delete("/{client_id}")
def delete_client(client_id: int, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    client = db.query(Client).get(client_id)
    if not client:
        raise HTTPException(404, "Cliente não encontrado")
    db.delete(client)
    db.commit()
    return {"ok": True}
