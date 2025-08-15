from collections.abc import Iterator
import datetime
import os
from pathlib import Path
import shutil
from typing import List, Optional
from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.config import app_config
from app.core.auth import validate_token
from app.core.models import Project
from app.util import logger, is_valid_filename
from niceview.dataadapter import ModelDataAdapter

###############################################################################

PROJECT_FILE_NAME = '.project.json'

###############################################################################

def get_project_path(project_name: str, check_project_exists: bool = True) -> Path:
    """
    Get (and check) the project path.

    :param project_name: The name of the project.
    :param check_project_exists: Whether to check if the project exists (default: True).
    :return: The absolute path to the project directory.
    :raises HTTPException: If the project name is invalid (400 Bad Request).
    :raises HTTPException: If the project does not exist (404 Not Found).
    """
    if not is_valid_filename(project_name):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid project name: {project_name}")

    base_path = Path(app_config.projects_dir).resolve()
    project_path = (base_path / project_name).resolve()
    if not project_path.is_relative_to(base_path):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid project path: {project_path}")

    if check_project_exists and not project_path.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project {project_name} does not exist.")

    return project_path


###############################################################################
# Project CRUD operations
###############################################################################

def create_project(project: Project) -> Project:
    """
    Create a new project.

    :param project: The project object to create.
    :return: The created project object.
    :raises HTTPException: If the project name is invalid (400 Bad Request).
    :raises HTTPException: If the project already exists (409 Conflict).
    """
    project_path = get_project_path(project.name, check_project_exists=False)

    try:
        project_path.mkdir(exist_ok=False)
    except FileExistsError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Project {project.name} already exists.")

    try:
        project_file = project_path / PROJECT_FILE_NAME
        now = datetime.datetime.now(datetime.timezone.utc)
        project.created_at = now
        project.updated_at = now
        temp_file = project_file.with_suffix('.tmp')
        temp_file.write_text(project.model_dump_json(indent=2))
        temp_file.rename(project_file)
    except Exception as e:
        logger.error(f"Error creating project {project_path}: {str(e)}")
        shutil.rmtree(project_path, ignore_errors=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error creating project: {str(e)}")
    return project


def get_project(project_name: str, check_active: bool = False) -> Project:
    """
    Get a project by name.

    :param project_name: The name of the project.
    :return: The requested project object.
    :raises HTTPException: If the project does not exist (404 Not Found).
    """
    project_path = get_project_path(project_name)
    project_file = project_path / PROJECT_FILE_NAME
    if project_file.is_file():
        try:
            json_data = project_file.read_text()
            project = Project.model_validate_json(json_data)
            project.name = project_name
        except Exception as e:
            logger.error(f"Error reading project file {project_file}: {str(e)}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error reading project file {project_file}: {str(e)}")
    else:
        # Create a new project object with the directory name
        stat_info = project_path.stat()
        project = Project(
            name=project_name,
            created_at=datetime.datetime.fromtimestamp(stat_info.st_ctime),
            updated_at=datetime.datetime.fromtimestamp(stat_info.st_mtime),
        )

    if not project.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Project {project_name} is not active.")

    return project


def update_project(project: Project) -> Project:
    """
    Update (save) a project.

    :param project: The project object to save.
    :return: The saved project object.
    :raises HTTPException: If the project path is invalid (400 Bad Request).
    """
    project_path = get_project_path(project.name)
    project_file = project_path / PROJECT_FILE_NAME
    try:
        project.updated_at = datetime.datetime.now(datetime.timezone.utc)
        temp_file = project_file.with_suffix('.tmp')
        temp_file.write_text(project.model_dump_json(indent=2))
        temp_file.rename(project_file)
    except Exception as e:
        logger.error(f"Error saving project {project_path}: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error saving project: {str(e)}")
    return project


def rename_project(old_project_name: str, new_project_name: str) -> Project:
    """
    Rename a project.

    :param old_project_name: The current name of the project.
    :param new_project_name: The new name for the project.
    :return: The updated project object.
    :raises HTTPException: If the project path is invalid (400 Bad Request).
    :raises HTTPException: If the new project name already exists (409 Conflict).
    """
    old_project_path = get_project_path(old_project_name)
    new_project_path = get_project_path(new_project_name, check_project_exists=False)

    if new_project_path.exists():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Project {new_project_name} already exists.")

    try:
        old_project_path.rename(new_project_path)
        return get_project(new_project_name)
    except Exception as e:
        logger.error(f"Error renaming project {old_project_path} to {new_project_path}: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error renaming project: {str(e)}")


def delete_project(project_name: str) -> None:
    """
    Delete a project.

    :param project_name: The name of the project.
    :raises HTTPException: If the project path is invalid (400 Bad Request).
    """
    project_path = get_project_path(project_name)
    try:
        if not project_path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project {project_name} does not exist.")
        shutil.rmtree(project_path)
    except Exception as e:
        logger.error(f"Error deleting project {project_path}: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error deleting project: {str(e)}")

###################################################################################

def get_projects() -> List[Project]:
    """
    Get all projects.

    :return: A list of all projects.
    """
    base_path = Path(app_config.projects_dir).resolve()
    projects = []
    for project_path in base_path.iterdir():
        if not project_path.is_dir() or not is_valid_filename(project_path.name):
            continue
        try:
            project = get_project(project_path.name)
            if project is not None:
                projects.append(project)
        except Exception as e:
            logger.error(f"Error reading project directory {project_path}: {str(e)}")
            pass
    return projects

###################################################################################

def get_auth_project(project_name: str, provisioning_token: str) -> Project:
    """
    Get the project if successful authentication using the given provisioning token or throw an exception.

    :param project_name: The name of the project.
    :param provisioning_token: The provisioning token for the project.
    :return: The project object.
    :raises HTTPException: If the project name is invalid (400 Bad Request).
    :raises HTTPException: If the project (provisioning) token is invalid or expired (401 Unauthorized).
    :raises HTTPException: If the project is not active (403 Forbidden).
    :raises HTTPException: If the project does not exist (404 Not Found).
    """
    project = get_project(project_name, check_active=True)
    token = validate_token(provisioning_token, project.provisioning_tokens)

    # update the project info
    for i, t in enumerate(project.provisioning_tokens):
        if t.value == token.value:
            project.provisioning_tokens[i].last_use_at = datetime.datetime.now(datetime.timezone.utc)
            break
    project = update_project(project)

    return project

###################################################################################
# Provide operations on the Project model in a nice interface for the UI
###################################################################################

class ProjectModelAdapter(ModelDataAdapter[Project]):
    """
    An adapter for a list of projects to work with the ModelGrid.
    """
    def __init__(self) -> None:
        pass

    def __iter__(self) -> Iterator[Project]:
        projects = get_projects()
        return iter(projects)

    def query_all_strs(self) -> Iterator[tuple[str, str]]:
        projects = get_projects()
        for index, item in enumerate(projects):
            yield self.key_from_item(item, index), item.name

    def key_from_item(self, item: Project, index: int = -1) -> str:
        key = item.name
        return key

    def key_from_str(self, key: str | int) -> str:
        return str(key)

    def create(self, item: Project) -> Project:
        if not isinstance(item, Project):
            raise TypeError(f"Expected item to be an instance of 'Project', got '{type(item)}'")
        create_project(item)
        return item

    def read(self, key: str | int) -> Project:
        if not isinstance(key, str):
            raise TypeError(f"Expected key to be a string, got {type(key)}")
        project = get_project(key)
        return project

    def update(self, item: Project, key: str) -> Project:
        if not isinstance(item, Project):
            raise TypeError(f"Expected item to be an instance of 'Project', got '{type(item)}'")
        if not isinstance(key, str):
            raise TypeError(f"Expected key to be a string, got {type(key)}")
        if key != item.name:
           rename_project(old_project_name=key, new_project_name=item.name)
        project = update_project(item)
        return project

    def delete(self, key: str) -> None:
        if not isinstance(key, str):
            raise TypeError(f"Expected key to be a string, got {type(key)}")
        delete_project(key)

