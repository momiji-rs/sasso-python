#!/usr/bin/env python3
"""Build the vendored ``native/`` cdylib for the host platform and copy the
resulting shared library into ``src/sasso/`` so the wheel can bundle it.

This is a ctypes binding, NOT a CPython C-extension: the produced
``libsasso.{so,dylib}`` / ``sasso.dll`` has no Python-ABI linkage, so a single
build serves every Python 3.x on that (OS, arch). Run this once before building
the wheel:

    python scripts/build_native.py
    python -m build --wheel
    # then retag the wheel with the platform tag (see README / release.yml)

Pass ``--target <triple>`` to cross-compile (the lib is copied from
``native/target/<triple>/release/``); otherwise the host target is used.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NATIVE_DIR = ROOT / "native"
PKG_DIR = ROOT / "src" / "sasso"

# cargo's output filename for `[lib] name = "sasso"`, per host OS.
_ARTIFACT = {
    "linux": "libsasso.so",
    "darwin": "libsasso.dylib",
    "win32": "sasso.dll",
}


def _host_artifact_name() -> str:
    if sys.platform.startswith("linux"):
        return _ARTIFACT["linux"]
    if sys.platform == "darwin":
        return _ARTIFACT["darwin"]
    if sys.platform == "win32":
        return _ARTIFACT["win32"]
    raise SystemExit(f"unsupported platform: {sys.platform!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        default=None,
        help="Rust target triple to build for (default: host).",
    )
    args = parser.parse_args()

    cargo_cmd = ["cargo", "build", "--release", "--manifest-path", str(NATIVE_DIR / "Cargo.toml")]
    if args.target:
        cargo_cmd += ["--target", args.target]

    print("+", " ".join(cargo_cmd), flush=True)
    subprocess.run(cargo_cmd, check=True)

    artifact = _host_artifact_name()
    if args.target:
        built = NATIVE_DIR / "target" / args.target / "release" / artifact
    else:
        built = NATIVE_DIR / "target" / "release" / artifact

    if not built.exists():
        raise SystemExit(f"expected built library not found: {built}")

    PKG_DIR.mkdir(parents=True, exist_ok=True)
    dest = PKG_DIR / artifact
    shutil.copy2(built, dest)
    print(f"copied {built} -> {dest}", flush=True)

    # On macOS, cargo bakes the build machine's absolute path into the dylib's
    # install name (LC_ID_DYLIB). The package loads the lib by absolute path via
    # ctypes.CDLL, so loading does not depend on this, but a machine-specific
    # install name is brittle and noisy — rewrite it to a relocatable @rpath
    # form so the shipped artifact is clean and reproducible. (delocate-wheel in
    # CI then completes the macOS wheel repair.)
    if sys.platform == "darwin":
        install_name = f"@rpath/{artifact}"
        try:
            subprocess.run(
                ["install_name_tool", "-id", install_name, str(dest)],
                check=True,
            )
            print(f"set install name -> {install_name}", flush=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            # Non-fatal: loading works regardless (CDLL uses the absolute path).
            print(f"warning: could not rewrite install name ({exc})", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
