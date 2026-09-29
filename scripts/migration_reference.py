"""Launch the unchanged Python reference with worktree-local state, initially offline."""

import argparse
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=REPO_ROOT / ".migration-local" / "reference")
    parser.add_argument("--check", action="store_true", help="Check isolated storage without starting the GUI")
    parser.add_argument("--self-test", action="store_true", help="Run the GUI startup self-test and exit")
    args = parser.parse_args()
    if Path.cwd().resolve() != REPO_ROOT:
        parser.error("Run this script from the worktree root so reference assets can be resolved.")

    state_dir = args.state_dir.resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(REPO_ROOT))

    # These process-local overrides leave the reference source and stable data intact.
    # Install them before importing main_gui or the FFT singleton.
    from src.core.config_manager import ConfigManager

    with (
        patch.dict(os.environ, {"XDG_DATA_HOME": str(state_dir / "data"), "MEASURELAB_TESTING": "0"}),
        patch.object(ConfigManager, "get_user_data_dir", staticmethod(lambda: str(state_dir))),
        patch.object(
            ConfigManager, "_get_default_screenshot_dir", staticmethod(lambda: str(state_dir / "screenshots"))
        ),
        patch.object(ConfigManager, "_resolve_config_path", lambda self, filename: str(state_dir / filename)),
    ):
        config = ConfigManager()
        # Start each reference session offline; hardware comparison is a later task.
        config.config["audio"]["offline_mode"] = True
        config.config["audio"]["pipewire_jack_resident"] = False
        config.save_config(force_sync=True)

        if args.check:
            from src.core.calibration import CalibrationManager
            from src.core.fft_manager import fft_manager

            print(
                json.dumps(
                    {
                        "source_root": str(REPO_ROOT),
                        "config": config.config_path,
                        "calibration": CalibrationManager().config_path,
                        "fft_wisdom": str(fft_manager.wisdom_path),
                        "log": str(state_dir / "measurelab.log"),
                        "screenshots": config.get_screenshot_output_dir(),
                        "offline_mode": config.is_offline_mode(),
                    },
                    indent=2,
                )
            )
            return

        import main_gui

        sys.argv = [str(REPO_ROOT / "main_gui.py")]
        if args.self_test:
            sys.argv.append("--self-test")
        main_gui.main()


if __name__ == "__main__":
    # Keep the VST helper's process entry-point behavior aligned with main_gui.py.
    import multiprocessing

    multiprocessing.freeze_support()
    main()
