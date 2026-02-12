---
description: Instructions for running development tools (pytest, ruff, mypy)
---

# Tool Usage Guide

## Virtual Environment Tools

For most development tools, you MUST use the executables located in `.venv/bin/`.
This is critical for ensuring the correct versions and configuration are used.

- `pytest` -> `.venv/bin/pytest` (run tests)
- `ruff`   -> `.venv/bin/ruff` (linter/formatter)
- `mypy`   -> `.venv/bin/mypy` (type checker)

## System/Global Tools

- `git`    -> `git` (version control)
- `mypy`   -> `mypy` (do not use system mypy, use venv one)

## Usage Examples

### Run Tests

```bash
/slash-command test
```

### Run Linter

```bash
/slash-command lint
```

### Run Type Checker

```bash
/slash-command typecheck
```
