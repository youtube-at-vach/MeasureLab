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

## Markdown Lint

This project uses `markdownlint-cli2` for Markdown quality checks.

- Remove trailing spaces and keep proper blank lines around headings, lists, and code blocks.
- Keep list marker/numbering style consistent.
- Wrap bare URLs with angle brackets like `<https://example.com>`.

Run after editing docs:

```bash
npx markdownlint-cli2 "**/*.md" "#node_modules"
```
