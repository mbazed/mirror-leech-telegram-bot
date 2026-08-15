#!/usr/bin/env python3
"""Standalone test harness for the gdflix Cloudflare-aware bypasser.

Usage:
    python3 test_gdflix_bypass.py <gdflix_url>

This imports only the resolver module (not the full bot package), so it can
run in a lightweight Python environment that has curl_cffi installed.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODULE_PATH = ROOT / "bot" / "helper" / "mirror_leech_utils" / "download_utils" / "gdflix_bypass.py"
EXCEPTIONS_PATH = ROOT / "bot" / "helper" / "ext_utils" / "exceptions.py"

_PACKAGES = {
    "bot": ROOT / "bot",
    "bot.helper": ROOT / "bot" / "helper",
    "bot.helper.ext_utils": ROOT / "bot" / "helper" / "ext_utils",
    "bot.helper.mirror_leech_utils": ROOT / "bot" / "helper" / "mirror_leech_utils",
    "bot.helper.mirror_leech_utils.download_utils": ROOT
    / "bot"
    / "helper"
    / "mirror_leech_utils"
    / "download_utils",
}


def _install_package_placeholders() -> None:
    for name, path in _PACKAGES.items():
        if name in sys.modules:
            continue
        module = types.ModuleType(name)
        module.__path__ = [str(path)]
        sys.modules[name] = module


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: python3 {sys.argv[0]} <gdflix_url>")
        return 2

    url = sys.argv[1]
    _install_package_placeholders()
    _load_module("bot.helper.ext_utils.exceptions", EXCEPTIONS_PATH)
    gdflix = _load_module(
        "bot.helper.mirror_leech_utils.download_utils.gdflix_bypass",
        MODULE_PATH,
    )
    exceptions = sys.modules["bot.helper.ext_utils.exceptions"]

    try:
        resolved = gdflix.gdflix_bypass(url)
    except exceptions.DirectDownloadLinkException as exc:
        print(f"BYPASS FAILED: {exc}")
        return 1

    print(f"BYPASSED URL: {resolved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
