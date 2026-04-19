"""
Child profile management.
"""
import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Child

router = APIRouter(prefix="/children", tags=["children"])


class ChildCreate(BaseModel):
    name: str
    birth_date: Optional[datetime.date] = None


class ChildOut(BaseModel):
    id: int
    name: str
    birth_date: Optional[datetime.datetime]
    created_at: datetime.datetime

    class Config:
        from_attributes = True


@router.post("", response_model=ChildOut, status_code=201)
async def create_child(data: ChildCreate, db: AsyncSession = Depends(get_db)):
    child = Child(
        name=data.name,
        birth_date=datetime.datetime.combine(data.birth_date, datetime.time()) if data.birth_date else None,
    )
    db.add(child)
    await db.commit()
    await db.refresh(child)
    return child


@router.get("", response_model=list[ChildOut])
async def list_children(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Child).order_by(Child.created_at))
    return result.scalars().all()


@router.get("/{child_id}", response_model=ChildOut)
async def get_child(child_id: int, db: AsyncSession = Depends(get_db)):
    child = await db.get(Child, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    return child


@router.delete("/{child_id}", status_code=204)
async def delete_child(child_id: int, db: AsyncSession = Depends(get_db)):
    child = await db.get(Child, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    await db.delete(child)
    await db.commit()
