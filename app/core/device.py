from pathlib import Path
import datetime
import shutil
from typing import List, Optional, Tuple
from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.config import app_config
from app.core.auth import create_token, validate_token
from app.core.models import AuthToken, Device, Project
from app.core.project import get_project, get_project_path
from app.util import logger, is_valid_filename


###############################################################################

DEVICE_FILE_NAME = '.device.json'

###############################################################################

def get_device_path(project_name: str, device_name: str, check_device_exists: bool = True) -> Path:
    """
    Get (and check) the device path.
    This function checks if the project and device names are valid.
    It also checks if the project path is relative to the projects directory.
    If also checks if the project exists and by default also if the device exists.

    :param project_name: The name of the project.
    :param device_name: The name of the device.
    :param check_device_exists: Whether to check if the device exists (default: True).
    :return: The absolute path to the device directory.
    :raises HTTPException: If the project name or the device name is invalid (400 Bad Request).
    :raises HTTPException: If the project does not exist (404 Not Found).
    :raises HTTPException: If the respective check is enabled and the device does not exist (404 Not Found).
    """
    if not is_valid_filename(device_name):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid device name: {device_name}")

    project_path = get_project_path(project_name)
    device_path = (project_path / device_name).resolve()
    if not device_path.is_relative_to(project_path):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid device path: {device_path}")

    if check_device_exists and not device_path.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Device {project_name}/{device_name} does not exist.")

    return device_path


def get_file_path(project_name: str, device_name: str, filename: str, check_file_exists: bool = True) -> Path:
    """
    Get (and check) the path for a device file (either from the device or from the project)
    in a similar way as the get_device_path function.

    :param project_name: The name of the project.
    :param device_name: The name of the device.
    :param filename: The name of the file to retrieve.
    :param check_file_exists: Whether to check if the file exists (default: True).
    :return: The absolute path to the file.
    :raises HTTPException: If the project name or the device name or the file name is invalid (400 Bad Request).
    :raises HTTPException: If the project or the device does not exist (404 Not Found).
    :raises HTTPException: If the respective check is enabled and the file does not exist (404 Not Found).
    """

    project_path = get_project_path(project_name)
    device_path = get_device_path(project_name, device_name)

    project_file_path = (project_path / filename).resolve()
    device_file_path = (device_path / filename).resolve()
    if not device_file_path.is_relative_to(device_path) or not project_file_path.is_relative_to(project_path):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file path: {filename}")
    
    if check_file_exists:
        path = device_file_path if device_file_path.is_file() else project_file_path
        if not path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"File not found: {project_name}/{device_name}/{filename}")
    else:
        path = device_file_path
    return path


###############################################################################
# Device CRUD operations
###############################################################################

def create_device(device: Device) -> Device:
    """
    Create a new device.

    :param device: The device object to create.
    :return: The created device object.
    :raises HTTPException: If the project or device name is invalid (400 Bad Request).
    :raises HTTPException: If the project or the device does not exist (404 Not Found).
    :raises HTTPException: If the device already exists (409 Conflict).
    """
    device_path = get_device_path(device.project_name, device.name, check_device_exists=False)

    # Create the device directory with the .device.json file
    try:
        device_path.mkdir(exist_ok=False)
    except FileExistsError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Device {device.project_name}/{device.name} already exists.")

    try:
        device_file = device_path / DEVICE_FILE_NAME
        now = datetime.datetime.now(datetime.timezone.utc)
        device.created_at = now
        device.updated_at = now
        temp_file = device_file.with_suffix('.tmp')
        temp_file.write_text(device.model_dump_json(indent=2))
        temp_file.rename(device_file)
    except Exception as e:
        logger.error(f"Error creating device {device_path}: {str(e)}")
        shutil.rmtree(device_path, ignore_errors=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error creating device: {str(e)}")
    return device


def get_device(project_name: str, device_name: str, check_active: bool = False) -> Device:
    """
    Get a device by name.

    :param project_name: The name of the project.
    :param device_name: The name of the device.
    :return: The requested device object.
    :raises HTTPException: If the project or device name is invalid (400 Bad Request).
    :raises HTTPException: If the project or the device does not exist (404 Not Found).
    :raises HTTPException: If check_active=True and the project or the device is not active (403 Forbidden).
    """
    device_path = get_device_path(project_name, device_name)

    # Check if the directory contains a .device.json file
    device_file = device_path / DEVICE_FILE_NAME
    if device_file.is_file():
        try:
            json_data = device_file.read_text()
            device = Device.model_validate_json(json_data)
            device.name = device_name
        except Exception as e:
            logger.error(f"Error reading device file {device_file}: {str(e)}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error reading device file {device_file}: {str(e)}")
    else:
        # Create a new device object with the directory name and created_at, updated_at
        stat_info = device_path.stat()
        device = Device(
            name=device_name,
            project_name=project_name, 
            created_at=datetime.datetime.fromtimestamp(stat_info.st_ctime),
            updated_at=datetime.datetime.fromtimestamp(stat_info.st_mtime),
        )
    
    if check_active and (not device.is_active or not get_project(project_name).is_active):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Project or device {project_name}/{device_name} is not active.")

    return device


def update_device(device: Device) -> Device:
    """
    Update (save) a device.

    :param device: The device object to save.
    :return: The saved device object.
    :raises HTTPException: If the project or device name is invalid (400 Bad Request).
    :raises HTTPException: If the project or the device does not exist (404 Not Found).
    """
    device_path = get_device_path(device.project_name, device.name)
    device_file = device_path / DEVICE_FILE_NAME
    try:
        device.updated_at = datetime.datetime.now(datetime.timezone.utc)
        temp_file = device_file.with_suffix('.tmp')
        temp_file.write_text(device.model_dump_json(indent=2))
        temp_file.rename(device_file)
    except Exception as e:
        logger.error(f"Error saving device {device_path}: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error saving device: {str(e)}")
    return device


def delete_device(project_name: str, device_name: str) -> None:
    """
    Delete a device.

    :param project_name: The name of the project.
    :param device_name: The name of the device.
    :raises HTTPException: If the project or device name is invalid (400 Bad Request).
    :raises HTTPException: If the project or the device does not exist (404 Not Found).
    """
    device_path = get_device_path(project_name, device_name)
    try:
        shutil.rmtree(device_path)
    except Exception as e:
        logger.error(f"Error deleting device {device_path}: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error deleting device: {str(e)}")


###############################################################################

def get_devices(project_name: str) -> List[Device]:
    """
    Get all devices.

    :param project_name: The name of the project.
    :return: A list of all devices in the project.
    :raises HTTPException: If the project name is invalid (400 Bad Request).
    :raises HTTPException: If the project does not exist (404 Not Found).
    """
    project_path = get_project_path(project_name)
    devices = []
    for device_path in project_path.iterdir():
        if not device_path.is_dir() or not is_valid_filename(device_path.name):
            continue
        try:
            device = get_device(project_name, device_path.name)
            if device is not None:
                devices.append(device)
        except Exception as e:
            logger.error(f"Error reading device file {device_path}: {str(e)}")
            pass
    return devices

###############################################################################

def get_auth_project_device(project_name: str, device_name: str, device_token: str) -> Tuple[Project, Device]:
    """
    Get the project and the device as a tuple if authenticated or throw an exception.

    :param project_name: The name of the project.
    :param device_name: The name of the device.
    :param device_token: The authentication token for the device.
    :return: A tuple containing the project and device objects.
    :raises HTTPException: If the project or device name is invalid (400 Bad Request).
    :raises HTTPException: If the project or the device does not exist (404 Not Found).
    :raises HTTPException: If the project or device is not active (403 Forbidden).
    :raises HTTPException: If the device token is invalid or expired (401 Unauthorized).
    """
    project = get_project(project_name, check_active=True)
    device = get_device(project_name, device_name, check_active=True)
    token = validate_token(device_token, device.tokens)

    # update the device info
    for i, t in enumerate(device.tokens):
        if t.value == token.value:
            device.tokens[i] = token
            break
    device.last_seen_at = datetime.datetime.now(datetime.timezone.utc)
    device = update_device(device)

    return project, device


###############################################################################

def device_provision(project: Project, device_name: str) -> str:
    """
    Provision a device and return the device authentication token.

    :param project: The project to which the device belongs.
    :param device_name: The name of the device to provision.
    :return: The authentication token for the provisioned device.
    :raises HTTPException: If the device name is invalid (400 Bad Request).
    :raises HTTPException: If the project is not active or the device is not active (403 Forbidden).
    :raises HTTPException: If the device is not approved for provisioning (403 Forbidden).
    :raises HTTPException: If the device does not exist and autocreate is disabled (404 Not Found).
    """
    # Check if the project is active
    if not project.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Project {project.name} is not active.")

    now = datetime.datetime.now(datetime.timezone.utc)

    # Check if the device already exists
    try:
        device = get_device(project.name, device_name)
    except HTTPException as e:
        if e.status_code == status.HTTP_404_NOT_FOUND:
            if not project.is_autocreate_devices:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Device {device_name} does not exist and autocreate is disabled.")
            # Create a new device
            device = create_device(Device(name=device_name, project_name=project.name, is_provisioning_approved=project.is_provisioning_autoapproval))
        else:
            raise

    device.last_provisioning_request_at = now

    # Device exists, check if it is active
    if not device.is_active:
        device = update_device(device)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Device {device_name} is not active.")
    
    if not device.is_provisioning_approved:
        device = update_device(device)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Device {device_name} is not approved for provisioning.")
    
    token = create_token(project.device_tokens_expire_in, app_config.device_token_length)
    device.tokens.append(token)
    device.last_provisioned_at = now
    device = update_device(device)

    return token.value
