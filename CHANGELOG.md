# Changelog

All notable changes to this project are documented here. Per `CLAUDE.md`, every
API change must be recorded. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Fixed

- Corrected the `POST /api/provision` 400-response description in the OpenAPI
  docs: project and device names must match `[a-zA-Z_][a-zA-Z0-9_]*` (letters,
  digits and underscore, no leading digit), not the `-`/`+` the text previously
  claimed. Only the documentation was wrong; validation was already stricter.

_0.9.0 is the first release; pre-release history is in the git log._
