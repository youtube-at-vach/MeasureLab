---
description: Instructions for running development tools (pytest, ruff, mypy)
---
# Tool Locations

## Virtual Environment Tools
For most development tools, you MUST use the executables located in `.venv/bin/`.
This is critical for ensuring the correct versions and configuration are used.

**Tools in `.venv/bin/` include:**
- `pytest` -> `.venv/bin/pytest`
- `ruff`   -> `.venv/bin/ruff`

## System/Global Tools
**Mypy** is NOT located in the virtual environment. Use the system default or globally installed version.
- `mypy`   -> `mypy` (do not look in `.venv/bin/mypy`)

# Usage Examples

## Run Tests
```bash
.venv/bin/pytest tests/
```

## Run Linter
```bash
.venv/bin/ruff check .
```

## Run Type Checker
```bash
mypy src/
```
