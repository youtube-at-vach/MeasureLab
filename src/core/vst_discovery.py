"""Find installed VST3 files/bundles without executing third-party code."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
import os
from pathlib import Path
import sys


def vst3_search_paths() -> list[Path]:
    """Standard user/global locations, in user-first priority order."""
    home = Path.home()
    platform = sys.platform
    if platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData/Local")
        program_files = Path(os.environ.get("ProgramFiles") or "C:/Program Files")
        common = Path(os.environ.get("CommonProgramFiles") or program_files / "Common Files")
        # CommonProgramFiles follows the running process's bitness. Do not
        # advertise the separate x86 directory to a 64-bit host.
        return [local / "Programs/Common/VST3", common / "VST3"]
    if platform == "darwin":
        return [
            home / "Library/Audio/Plug-Ins/VST3",
            Path("/Library/Audio/Plug-Ins/VST3"),
            Path("/Network/Library/Audio/Plug-Ins/VST3"),
        ]
    if platform.startswith("linux"):
        return [
            home / ".vst3",
            Path("/usr/lib64/vst3"),
            Path("/usr/lib/vst3"),
            Path("/usr/local/lib64/vst3"),
            Path("/usr/local/lib/vst3"),
        ]
    return []


@dataclass
class VstScanResult:
    paths: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def discover_vst3(roots: Iterable[Path] | None = None, *, cancelled: Callable[[], bool] | None = None) -> VstScanResult:
    """Recurse vendor folders, treating a .vst3 bundle as a single entry.

    Resolve links to deduplicate aliases and avoid directory cycles. Missing
    default locations are normal; other access failures are reported to the UI.
    This is discovery only: architecture/effect compatibility is checked on load.
    """
    result = VstScanResult()
    pending = list(reversed(list(vst3_search_paths() if roots is None else roots)))
    seen: set[Path] = set()
    while pending:
        if cancelled is not None and cancelled():
            break
        path = pending.pop()
        try:
            resolved = path.expanduser().resolve(strict=True)
            if resolved in seen:
                continue
            seen.add(resolved)
            if path.suffix.lower() == ".vst3":
                if resolved.is_file() or resolved.is_dir():
                    result.paths.append(path.expanduser().absolute())
                continue
            if resolved.is_dir():
                pending.extend(sorted(resolved.iterdir(), key=lambda p: p.name.casefold(), reverse=True))
        except FileNotFoundError:
            continue  # Missing roots, broken links, or removal during a scan.
        except (OSError, RuntimeError) as exc:
            result.errors.append(f"{path}: {exc}")
    result.paths.sort(key=lambda p: (p.stem.casefold(), str(p).casefold()))
    return result
