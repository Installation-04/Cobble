"""Project endpoints, scoped to the authenticated owner."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response
from sqlalchemy import select

from cobble.db import Folder, Project

from .deps import CurrentUser, Db, parse_id
from .errors import ApiError
from .schemas import ProjectIn, ProjectOut, ProjectPatch

router = APIRouter()


def _owned(db: Db, user: CurrentUser, project_id: str) -> Project:
    project = db.scalars(
        select(Project).where(Project.id == parse_id(project_id), Project.owner_id == user.id)
    ).first()
    if project is None:
        raise ApiError(404, "not_found")
    return project


def _check_folder(db: Db, user: CurrentUser, folder_id: uuid.UUID) -> None:
    found = db.scalars(
        select(Folder.id).where(Folder.id == folder_id, Folder.owner_id == user.id)
    ).first()
    if found is None:
        raise ApiError(404, "not_found")


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(user: CurrentUser, db: Db) -> list[Project]:
    stmt = select(Project).where(Project.owner_id == user.id).order_by(Project.created_at)
    return list(db.scalars(stmt))


@router.post("/projects", status_code=201, response_model=ProjectOut)
def create_project(body: ProjectIn, user: CurrentUser, db: Db) -> Project:
    if body.folder_id is not None:
        _check_folder(db, user, body.folder_id)
    project = Project(owner_id=user.id, name=body.name, folder_id=body.folder_id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: str, body: ProjectPatch, user: CurrentUser, db: Db) -> Project:
    project = _owned(db, user, project_id)
    if body.name is not None:
        project.name = body.name
    if "folder_id" in body.model_fields_set:
        if body.folder_id is not None:
            _check_folder(db, user, body.folder_id)
        project.folder_id = body.folder_id
    db.commit()
    return project


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str, user: CurrentUser, db: Db) -> Response:
    db.delete(_owned(db, user, project_id))
    db.commit()
    return Response(status_code=204)
