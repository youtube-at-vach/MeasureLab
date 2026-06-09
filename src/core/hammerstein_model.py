import json
import logging
from datetime import datetime
import numpy as np

logger = logging.getLogger(__name__)


def save_hammerstein_model(filepath, data):
    """
    Saves a Hammerstein model to a JSON file.

    data dict structure:
        - metadata (dict): setup parameters
        - time_domain (dict):
            - time_ms (np.ndarray or list)
            - kernels (dict of np.ndarray/list): h1 to h5
        - frequency_domain (dict):
            - freqs (np.ndarray or list)
            - magnitudes_db (dict of np.ndarray/list)
            - phases_deg (dict of np.ndarray/list)
    """
    try:
        # Construct JSON-serializable structure
        serializable_data = {
            "metadata": {
                "format_version": "1.0",
                "export_timestamp": datetime.now().isoformat(),
                **data.get("metadata", {}),
            },
            "time_domain": {
                "time_ms": list(data["time_domain"]["time_ms"]),
                "kernels": {
                    k: list(v) for k, v in data["time_domain"]["kernels"].items()
                },
            },
            "frequency_domain": {
                "freqs": list(data["frequency_domain"]["freqs"]),
                "magnitudes_db": {
                    k: list(v) for k, v in data["frequency_domain"]["magnitudes_db"].items()
                },
                "phases_deg": {
                    k: list(v) for k, v in data["frequency_domain"]["phases_deg"].items()
                },
            },
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(serializable_data, f, indent=2, ensure_ascii=False)
        logger.info("Successfully saved Hammerstein model to %s", filepath)
    except Exception as e:
        logger.error("Failed to save Hammerstein model: %s", e, exc_info=True)
        raise


def load_hammerstein_model(filepath):
    """
    Loads a Hammerstein model from a JSON file and restores arrays to numpy ndarrays.

    Returns:
        dict: The model data structure with np.ndarray objects.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        restored_data = {
            "metadata": raw_data.get("metadata", {}),
            "time_domain": {
                "time_ms": np.array(raw_data["time_domain"]["time_ms"], dtype=np.float32),
                "kernels": {
                    k: np.array(v, dtype=np.float32) for k, v in raw_data["time_domain"]["kernels"].items()
                },
            },
            "frequency_domain": {
                "freqs": np.array(raw_data["frequency_domain"]["freqs"], dtype=np.float32),
                "magnitudes_db": {
                    k: np.array(v, dtype=np.float32)
                    for k, v in raw_data["frequency_domain"]["magnitudes_db"].items()
                },
                "phases_deg": {
                    k: np.array(v, dtype=np.float32)
                    for k, v in raw_data["frequency_domain"]["phases_deg"].items()
                },
            },
        }
        logger.info("Successfully loaded Hammerstein model from %s", filepath)
        return restored_data
    except Exception as e:
        logger.error("Failed to load Hammerstein model: %s", e, exc_info=True)
        raise


# Decoupled active model cache for inter-module communication
_ACTIVE_MODEL_CACHE = None


def set_active_model(data):
    """
    Caches the active Hammerstein model in memory.
    data: dict containing model structure (metadata, time_domain, frequency_domain).
    """
    global _ACTIVE_MODEL_CACHE
    _ACTIVE_MODEL_CACHE = data


def get_active_model():
    """
    Retrieves the cached active Hammerstein model.
    Returns:
        dict: The model data, or None if no model is cached.
    """
    return _ACTIVE_MODEL_CACHE


def has_active_model():
    """
    Checks if an active Hammerstein model is cached.
    Returns:
        bool: True if cached, False otherwise.
    """
    return _ACTIVE_MODEL_CACHE is not None
