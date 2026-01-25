# Contributing to MeasureLab

We welcome contributions of all kinds! This document provides guidelines for contributing to MeasureLab, including how to set up your development environment and the workflow for submitting changes.

## AI-Assisted Pull Requests / AI 支援による Pull Request について

> [!IMPORTANT]
> **This project actively welcomes Pull Requests created with the help of AI tools.**
> In fact, development of this project proceeds on the premise of AI-assisted PRs.
>
> Contributions using AI—whether for code, documentation, analysis, or design proposals—are all welcome. We don't mind who wrote it or what tool was used; we focus on whether the content is clear and adds value to the project.
>
> You are encouraged to clone the repository using tools like GitHub Copilot or Antigravity and submit the results of your work with AI as a PR. A brief explanation of "what was done" and "why it was done" in the PR description is sufficient.
>
> Reviews involve both humans and AI. If CI tests pass successfully, changes will be merged into the `main` branch.
>
> ---
>
> **本プロジェクトでは、AI ツールを活用して作成された Pull Request を積極的に歓迎しています。**
> 実際に、このプロジェクトは AI 支援による PR を前提として開発が進んでいます。
>
> コード、ドキュメント、解析、設計案など、AI を使った貢献はすべて歓迎です。
> 誰が書いたかや、どのツールを使ったかはあまり気にしていません。
> 内容が分かりやすく、プロジェクトにとってプラスになりそうかどうかを重視しています。
>
> GitHub Copilot や Antigravity などを使ってリポジトリをクローンし、
> AI と一緒に作業した結果をそのまま PR として送ってもらって構いません。
> PR には「何をしたか」「なぜそうしたか」が軽く分かる説明があれば十分です。
>
> レビューには人間だけでなく AI も関与します。
> CI などのテストが問題なく通過すれば、main ブランチにマージされます。

---

## 🚀 Getting Started

To contribute to MeasureLab, you'll need to set up a development environment.

### Prerequisites

- **Python 3.10** or higher
- `pip` and `venv`
- **Node.js** (optional, for markdown linting)

### Setup Environment

1. **Clone the Repository**

    ```bash
    git clone <https://github.com/youtube-at-vach/MeasureLab.git>
    cd MeasureLab
    ```

2. **Create and Activate a Virtual Environment**

    ```bash
    python3 -m venv .venv
    source .venv/bin/activate  # On Linux/macOS
    # Or: .venv\Scripts\activate  # On Windows
    ```

3. **Install Dependencies**
    We use `constraints.txt` to ensure reproducible builds.

    ```bash
    pip install -U pip
    pip install -c constraints.txt -r requirements.txt
    ```

4. **Install Development Tools**

    ```bash
    pip install -c constraints.txt -e .[dev]
    ```

---

## 🛠️ Contribution Workflow

### 1. Create a Branch

Always create a new branch for your changes.

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

### 2. Make Your Changes

Implement your feature or fix. If you are using AI tools, feel free to use them to generate code, write tests, or update documentation.

### 3. Verify Your Changes

Before submitting a PR, ensure your changes meet the project's standards.

- **Linting:**

  ```bash
  ruff check src scripts tests
  ```

- **Type Checking:**

  ```bash
  mypy src
  ```

- **Testing:**

  ```bash
  pytest
  ```

  > [!NOTE]
  > Hardware or GUI-dependent tests might require specific environments and are typically skipped in CI by default.

- **Markdown Linting:**
  If you have Node.js installed, check the documentation style:

  ```bash
  npx markdownlint-cli2 "**/*.md" "#node_modules"
  ```

### 4. Commit and Push

```bash
git add .
git commit -m "Brief description of your changes"
git push origin feature/your-feature-name
```

### 5. Submit a Pull Request

Open a PR on GitHub. In the description, briefly explain:

- What you changed.
- Why you made the change.
- Any AI tools used (optional but appreciated).

---

## 📜 Coding Standards

- **Style:** We follow PEP 8 and use `ruff` for linting.
- **Types:** We use `mypy` for static type checking.
- **Localization:**
    - All GUI strings MUST be wrapped in `tr()` for internationalization.
    - Translation keys are stored in `src/assets/lang/*.json`.
    - Use `python scripts/check_trn_keys.py` to verify key consistency.
- **Markdown:**
    - We use `markdownlint-cli2` for documentation quality.
    - Wrap URLs in `< ... >` (e.g., `<https://example.com>`).
- **Adding Modules:**
    - When adding a new measurement module, update `_module_keys` and `_load_module_class()` in `src/gui/main_window.py`.
- **Documentation:** Keep documentation up to date (README, docstrings, etc.).
