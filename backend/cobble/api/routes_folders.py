"""Folder endpoints, scoped to the authenticated owner."""

from __future__ import annotations

from fastapi import APIRouter, Response
from sqlalchemy import func, select, update

from cobble.db import Folder, Project

from .deps import CurrentUser, Db, parse_id
from .errors import ApiError
from .schemas import FolderIn, FolderOut, FolderPatch

router = APIRouter()


def _owned(db: Db, user: CurrentUser, folder_id: str) -> Folder:
    folder = db.scalars(
        select(Folder).where(Folder.id == parse_id(folder_id), Folder.owner_id == user.id)
    ).first()
    if folder is None:
        raise ApiError(404, "not_found")
    return folder


@router.get("/folders", response_model=list[FolderOut])
def list_folders(user: CurrentUser, db: Db) -> list[Folder]:
    stmt = (
        select(Folder)
        .where(Folder.owner_id == user.id)
        .order_by(Folder.position, Folder.created_at)
    )
    return list(db.scalars(stmt))


@router.post("/folders", status_code=201, response_model=FolderOut)
def create_folder(body: FolderIn, user: CurrentUser, db: Db) -> Folder:
    last = db.scalar(select(func.max(Folder.position)).where(Folder.owner_id == user.id))
    folder = Folder(owner_id=user.id, name=body.name, position=0 if last is None else last + 1)
    db.add(folder)
    db.commit()
    return folder


@router.patch("/folders/{folder_id}", response_model=FolderOut)
def update_folder(folder_id: str, body: FolderPatch, user: CurrentUser, db: Db) -> Folder:
    folder = _owned(db, user, folder_id)
    if body.name is not None:
        folder.name = body.name
    db.commit()
    return folder


@router.delete("/folders/{folder_id}", status_code=204)
def delete_folder(folder_id: str, user: CurrentUser, db: Db) -> Response:
    folder = _owned(db, user, folder_id)
    # Unfile explicitly: SQLite (tests) does not enforce ON DELETE SET NULL.
    db.execute(update(Project).where(Project.folder_id == folder.id).values(folder_id=None))
    db.delete(folder)
    db.commit()
    return Response(status_code=204)
