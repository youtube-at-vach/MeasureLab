#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status
set -e

# Change to repository root directory, relative to this script's location
cd "$(dirname "$0")/.."

OS="$(uname -s)"
echo "Detected OS: ${OS}"

# Basic check to ensure we are in the project root
if [ ! -f "requirements.txt" ] || [ ! -f "constraints.txt" ]; then
    echo "Error: Cannot find requirements.txt or constraints.txt."
    echo "Make sure you are running this from the repository root or scripts directory."
    exit 1
fi

if [ "${OS}" = "Linux" ]; then
    echo "========================================"
    echo " Starting Linux Environment Setup"
    echo "========================================"
    
    if command -v apt > /dev/null; then
        echo "Installing OS dependencies via apt..."
        sudo apt update
        sudo apt install -y python3 python3-venv python3-pip libportaudio2 libsndfile1 build-essential portaudio19-dev libsndfile1-dev nodejs npm
    else
        echo "Warning: 'apt' package manager not found."
        echo "Please ensure the following are installed manually:"
        echo "- python3, python3-venv, python3-pip, nodejs, npm"
        echo "- libportaudio2, libsndfile1, build-essential, portaudio19-dev, libsndfile1-dev"
    fi

    echo "Creating virtual environment in .venv..."
    python3 -m venv .venv
    
    echo "Activating virtual environment..."
    source .venv/bin/activate
    
    echo "Upgrading pip..."
    python -m pip install -U pip

elif [ "${OS}" = "Darwin" ]; then
    echo "========================================"
    echo " Starting macOS Environment Setup"
    echo "========================================"
    
    if command -v port > /dev/null; then
        echo "Updating MacPorts..."
        sudo port selfupdate
        
        echo "Installing Python 3.12, pip, FFTW3, and Node.js via MacPorts..."
        sudo port install python312 py312-pip fftw-3 nodejs22 npm10
        
        read -p "Do you want to set Python 3.12 and Node.js 22 as system defaults via 'port select'? (y/N): " set_default
        if [[ "$set_default" =~ ^[Yy]$ ]]; then
            echo "Setting default python to python312..."
            sudo port select --set python python312
            sudo port select --set python3 python312
            
            echo "Setting default node and npm..."
            sudo port select --set node nodejs22
            sudo port select --set npm npm10
        else
            echo "Skipping 'port select'. If not set, you may need to call python3.12 and node/npm explicitly."
        fi
    else
        echo "Warning: MacPorts ('port') not found."
        echo "The development guide assumes MacPorts is used for this project."
        echo "If you use Homebrew, ensure Python 3.12+ and fftw3 are installed,"
        echo "and you may need to adjust the pyFFTW prefix paths if it fails."
        read -p "Press Enter to continue anyway, or Ctrl+C to abort..."
    fi

    PYTHON_BIN="python3.12"
    if ! command -v $PYTHON_BIN > /dev/null; then
        PYTHON_BIN="python3"
        echo "Warning: python3.12 command not found, falling back to ${PYTHON_BIN}"
    fi

    echo "Creating virtual environment in .venv..."
    $PYTHON_BIN -m venv .venv
    
    echo "Activating virtual environment..."
    # shellcheck source=/dev/null
    source .venv/bin/activate
    
    echo "Upgrading pip..."
    python -m pip install -U pip

    echo "Installing pyFFTW with explicit FFTW prefix (for macOS)..."
    PYFFTW_FFTW_PREFIX=/opt/local python -m pip install pyfftw --no-binary pyfftw

else
    echo "Error: Unsupported OS: ${OS}"
    echo "This script only supports Linux and macOS (Darwin)."
    exit 1
fi

echo "========================================"
echo " Installing Python Project Dependencies"
echo "========================================"

echo "Installing core requirements..."
python -m pip install -c constraints.txt -r requirements.txt

echo "Installing dev tools..."
python -m pip install -c constraints.txt -e ".[dev]"

echo "Installing doc requirements..."
python -m pip install -c constraints.txt -r requirements-docs.txt

echo ""
echo "============================================================"
echo " ✅ Development environment setup successfully completed!"
echo "============================================================"
echo "To start coding, activate the virtual environment by running:"
echo "    source .venv/bin/activate"
