import datetime
import shutil
from pathlib import Path

from niceview.dataadapter import JsonAdapter

from app.config import app_config
from app.exceptions import AlreadyExistsError, ForbiddenError, NotFoundError
from app.paths import project_dir
from app.core.token.backend import get_provisioning_token_adapter, validate_token
from app.core.project.models import Project
from app.util import logger, is_valid_name
from niceview.dataadapter import lenient_model_load

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
        NotFoundError: Directory does not exist.
    """
    path = project_dir(project_name)
    if not path.is_dir():
        raise NotFoundError(f"Project {project_name} does not exist.")
    return path


###############################################################################
# Project CRUD operations
###############################################################################

def create_project(project_name: str) -> Project:
    """Create a new project directory and write the initial JSON file.

    Raises:
        ValueError: Invalid project name.
        AlreadyExistsError: Project already exists.
        OSError: Directory or file could not be created.
    """
    project_path = project_dir(project_name)
    try:
        project_path.mkdir(exist_ok=False)
    except FileExistsError as e:
        raise AlreadyExistsError(f"Project {project_name} already exists.") from e
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        # Seed device-token fields from env (editable per project afterwards).
        project = Project(name=project_name, created_at=now, updated_at=now,
                          device_token_length=app_config.device_token_length,
                          device_tokens_expire_in=app_config.device_token_expires_in)
        JsonAdapter(Project, project_filename(project_name), create_if_not_exist=False).save(project)
        # Seed telemetry and logging config from the DEFAULT_* env vars, so a new
        # project starts on the shared backend without hand-configuring each one.
        # Local imports avoid an import cycle (those backends import paths/util).
        from app.core.telemetry.backend import get_telemetry_adapter, default_telemetry_config
        from app.core.logging.backend import get_logging_adapter, default_logging_config
        get_telemetry_adapter(project_name).save(default_telemetry_config())
        get_logging_adapter(project_name).save(default_logging_config())
    except Exception:
        shutil.rmtree(project_path, ignore_errors=True)
        raise
    return project


def get_project(project_name: str, check_active: bool = True) -> Project:
    """Load and return a project by name.

    Raises:
        ValueError: Invalid project name.
        NotFoundError: Project directory does not exist.
        ForbiddenError: check_active is True and project is not active.
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
        raise ForbiddenError(f"Project {project_name} is not active.")
    return project


def rename_project(old_project_name: str, new_project_name: str) -> None:
    """Rename a project (directory + name field in JSON).

    Raises:
        ValueError: Invalid name.
        NotFoundError: Old project does not exist.
        AlreadyExistsError: New project name is already taken.
        OSError: Rename failed.
    """
    old_project_path = get_project_path(old_project_name)
    new_project_path = project_dir(new_project_name)
    if new_project_path.exists():
        raise AlreadyExistsError(f"Project {new_project_name} already exists.")
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
        NotFoundError: Project does not exist.
        OSError: Directory could not be deleted.
    """
    project_path = get_project_path(project_name)
    shutil.rmtree(project_path)


def get_projects() -> list[Project]:
    """Return all projects (active and inactive), silently skipping any that fail to load."""
    base_path = Path(app_config.projects_dir).resolve()
    projects = []
    for project_path in base_path.iterdir():
        if not project_path.is_dir() or not is_valid_name(project_path.name):
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
    except ValueError as e:
        # invalid name — normalized to NotFoundError; NotFoundError itself propagates
        raise NotFoundError(str(e)) from e

    if not project.is_active:
        raise ForbiddenError(f"Project {project_name} is not active.")

    token_adapter = get_provisioning_token_adapter(project_name)
    # validate_token raises AuthError on failure
    token = validate_token(provisioning_token, list(token_adapter))
    token_adapter.update(token)

    return project
