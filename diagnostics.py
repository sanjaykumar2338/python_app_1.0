import locale
import os
import platform
import sys
from importlib import import_module
from typing import Dict, List, Tuple


def get_runtime_info() -> Dict[str, str]:
    return {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "exe_mode": "frozen" if getattr(sys, "frozen", False) else "script",
        "cwd": os.getcwd(),
        "fs_encoding": sys.getfilesystemencoding(),
        "preferred_encoding": locale.getpreferredencoding(False),
    }


def _safe_version(pkg: str) -> str:
    try:
        mod = import_module(pkg)
        return getattr(mod, "__version__", "unknown")
    except Exception:
        return "missing"


def get_dependency_versions() -> Dict[str, str]:
    libs = ["fitz", "pytesseract", "PIL", "pdfplumber"]
    return {lib: _safe_version(lib) for lib in libs}


def _which(cmd: str) -> str:
    from shutil import which

    return which(cmd) or ""


def check_external_deps() -> Dict[str, Dict[str, str]]:
    deps = {
        "tesseract": _which(os.environ.get("TESSERACT_CMD") or os.environ.get("TESSERACT_PATH") or "tesseract"),
        "poppler": _which("pdftoppm"),
    }
    return {k: {"path": v, "exists": bool(v)} for k, v in deps.items()}


def log_environment() -> Dict[str, Dict]:
    return {
        "runtime": get_runtime_info(),
        "deps": get_dependency_versions(),
        "external": check_external_deps(),
    }
