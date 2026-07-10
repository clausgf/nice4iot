import datetime
import shutil
from pathlib import Path

from niceview.dataadapter import JsonAdapter

from app.config import app_config
from app.exceptions import AuthError, ForbiddenError, NotFoundError
from app.paths import project_dir
from app.core.token.backend import get_provisioning_token_adapter, validate_token
from app.core.project.models import Project
from app.util import logger, is_valid_filename
from niceview.dataadapter import JsonAdapter, lenient_model_load

###############################################################################

PROJECT_FILENAME = '.project.json'

###############################################################################

def project_filename(project_name: str) -> Path:
    """Return the path to the project JSON file (no existence checks)."""
    return project_dir(project_name) / PROJECT_FILENAME


def project_adapter(project_name: str) -> JsonAdapter:
    """Return a JsonAdapter for the project file."""
    return JsonAdapter(Project,
                              project_filename(project_name),
                              create_if_not_exist=True,
                              created_field='created_at',
                              lock_field='updated_at')



def get_project_path(project_name: str) -> Path:
    """Return the project directory path after validating it exists.

    Raises:
        ValueError: Invalid name or path escapes the projects directory.
        FileNotFoundError: Directory does not exist.
    """
    path = project_dir(project_name)
    if not path.is_dir():
        raise FileNotFoundError(f"Project {project_name} does not exist.")
    return path


###############################################################################
# Project CRUD operations
###############################################################################

def create_project(project_name: str) -> Project:
    """Create a new project directory and write the initial JSON file.

    Raises:
        ValueError: Invalid project name.
        FileExistsError: Project already exists.
        OSError: Directory or file could not be created.
    """
    project_path = project_dir(project_name)
    project_path.mkdir(exist_ok=False)
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        project = Project(name=project_name, created_at=now, updated_at=now)
        JsonAdapter(Project, project_filename(project_name), create_if_not_exist=False).save(project)
    except Exception:
        shutil.rmtree(project_path, ignore_errors=True)
        raise
    return project


def get_project(project_name: str, check_active: bool = True) -> Project:
    """Load and return a project by name.

    Raises:
        ValueError: Invalid project name.
        FileNotFoundError: Project directory does not exist.
        PermissionError: check_active is True and project is not active.
        OSError: Project file could not be read.
    """
    project_path = get_project_path(project_name)
    project_file = project_filename(project_name)
    if project_file.is_file():
        project = lenient_model_load(Project, project_file.read_text(), str(project_file))
        project.name = project_name
    else:
        stat_info = project_path.stat()
        project = Project(
            name=project_name,
            created_at=datetime.datetime.fromtimestamp(stat_info.st_ctime, tz=datetime.timezone.utc),
            updated_at=datetime.datetime.fromtimestamp(stat_info.st_mtime, tz=datetime.timezone.utc),
        )
    if check_active and not project.is_active:
        raise PermissionError(f"Project {project_name} is not active.")
    return project


def rename_project(old_project_name: str, new_project_name: str) -> None:
    """Rename a project (directory + name field in JSON).

    Raises:
        ValueError: Invalid name.
        FileNotFoundError: Old project does not exist.
        FileExistsError: New project name is already taken.
        OSError: Rename failed.
    """
    old_project_path = get_project_path(old_project_name)
    new_project_path = project_dir(new_project_name)
    if new_project_path.exists():
        raise FileExistsError(f"Project {new_project_name} already exists.")
    old_project_path.rename(new_project_path)
    new_json = project_filename(new_project_name)
    if new_json.is_file():
        adapter = JsonAdapter(Project, new_json, create_if_not_exist=False, lock_field='updated_at')
        project_data = adapter.read()
        project_data.name = new_project_name
        adapter.save(project_data)


def delete_project(project_name: str) -> None:
    """Delete a project directory and all its contents.

    Raises:
        ValueError: Invalid project name.
        FileNotFoundError: Project does not exist.
        OSError: Directory could not be deleted.
    """
    project_path = get_project_path(project_name)
    shutil.rmtree(project_path)


def get_projects() -> list[Project]:
    """Return all projects (active and inactive), silently skipping any that fail to load."""
    base_path = Path(app_config.projects_dir).resolve()
    projects = []
    for project_path in base_path.iterdir():
        if not project_path.is_dir() or not is_valid_filename(project_path.name):
            continue
        try:
            projects.append(get_project(project_path.name, check_active=False))
        except Exception as e:
            logger.error(f"Error reading project directory {project_path}: {e}")
    return sorted(projects, key=lambda p: p.name)

###############################################################################

def get_auth_project(project_name: str, provisioning_token: str) -> Project:
    """Authenticate via provisioning token and return the project.

    Raises:
        NotFoundError: Project not found.
        ForbiddenError: Project is not active.
        AuthError: Provisioning token invalid or expired.
    """
    try:
        project = get_project(project_name, check_active=False)
    except (ValueError, FileNotFoundError) as e:
        raise NotFoundError(str(e)) from e

    if not project.is_active:
        raise ForbiddenError(f"Project {project_name} is not active.")

    token_adapter = get_provisioning_token_adapter(project_name)
    # validate_token raises AuthError on failure
    token = validate_token(provisioning_token, list(token_adapter))
    token_adapter.update(token)

    return project
