# Development Guide

Instructions for running from source code and setting up the development environment.

## 🐍 Running from Source Code

**Prerequisites**: Python 3.12 or higher

### 🚀 Automated Setup Script (Recommended)

For Linux (Ubuntu) and macOS environments, we provide a convenient script that automates everything from installing OS packages to creating a virtual environment (`.venv`) and installing necessary Python dependencies, Node.js, and other development tools.

Simply open your terminal and run the following command in the repository root directory:

```bash
./scripts/setup_dev_env.sh
```

* Note: During execution, you may be prompted to enter your password or confirm default settings for MacPorts.

Once the setup is complete, activate the virtual environment and launch the application using the following commands:

```bash
source .venv/bin/activate
python main_gui.py
```

### 🛠️ Manual Setup

If you prefer not to use the automated script and want to set up the environment manually, please follow the instructions below.

#### Linux / Ubuntu: Manual Virtual Environment (venv) Setup

While the release versions (AppImage/ZIP) work as is, when running from source code, **APT (OS package) Python dependencies (e.g., PyQt6) might be too old to work**.
Therefore, on Linux, it is recommended to **use the system Python but install dependent packages using venv + pip**.

1. Install OS dependent libraries (minimum requirements).
    * `sounddevice` uses PortAudio, so `libportaudio2` is required at runtime.
    * `soundfile` uses libsndfile, so `libsndfile1` is required at runtime.

    ```bash
    sudo apt update
    sudo apt install -y python3 python3-venv python3-pip libportaudio2 libsndfile1
    ```

    Only if you encounter build errors with `pip install`, install additional development headers:

    ```bash
    sudo apt install -y build-essential portaudio19-dev libsndfile1-dev
    ```

2. Create and activate a virtual environment (e.g., `.venv` under the repository root).

    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install -U pip
    ```

    From here on, `python` / `pip` refer to the venv (do not use `sudo pip`).

    * If you want to run without using `activate`, you can always call the venv Python directly:

    ```bash
    ./.venv/bin/python -m pip install -U pip
    ./.venv/bin/python -m pip install -c constraints.txt -r requirements.txt
    ./.venv/bin/python main_gui.py
    ```

3. Clone the repository.
4. Install dependencies (use constraints for reproducibility):

    ```bash
    pip install -c constraints.txt -r requirements.txt
    ```

5. Launch the application:

    ```bash
    python main_gui.py
    ```

#### macOS: Using MacPorts + Python 3.12 + pyFFTW

(Verified on macOS 13 or later)

When installing `pyFFTW` on macOS, you need to explicitly specify the FFTW library installed via a package manager (MacPorts recommended).

1. Update MacPorts and install required packages:

    ```bash
    sudo port selfupdate
    sudo port install python312 py312-pip fftw-3 fftw-3-single
    ```

2. Select Python version:

    ```bash
    sudo port select --set python python312
    sudo port select --set python3 python312
    ```

    * Restart the terminal after configuration.

3. Create and activate a virtual environment:

    ```bash
    python3.12 -m venv .venv
    source .venv/bin/activate
    python -m pip install -U pip
    ```

4. Install pyFFTW (Explicitly specifying the FFTW path):

    ```bash
    python -m pip cache remove pyfftw
    PYFFTW_FFTW_PREFIX=/opt/local \
    python -m pip install pyfftw --no-binary pyfftw
    ```

5. Install dependent packages:

    ```bash
    python -m pip install -c constraints.txt -r requirements.txt
    ```

### 🛠️ Development Setup

If you want to run tests, Lint/type checks, or build the documentation, install the additional packages.

* **Code Development (Tests/Lint, etc.)**:

    ```bash
    pip install -c constraints.txt -e ".[dev]"
    ```

    * If you are using zsh, you need to enclose `.[dev]` in quotes (e.g., `".[dev]"`).

* **Documentation Development (MkDocs)**:

    ```bash
    pip install -c constraints.txt -r requirements-docs.txt
    ```

* Lint: `ruff check src scripts tests`
* Type check: `mypy src`
* Tests: `pytest` (Hardware/GUI dependent tests require environment variables; skipped by default in CI)
