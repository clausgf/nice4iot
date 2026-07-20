#!/bin/sh
# Ensure the projects directory exists — app.config.AppConfig.projects_dir is a
# pydantic DirectoryPath and must exist at startup. Honours a PROJECTS_DIR
# override (same env var pydantic-settings reads). Then hand off to the CMD.
set -e
mkdir -p "${PROJECTS_DIR:-data/projects}"
exec "$@"
