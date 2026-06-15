#!/usr/bin/env python3
"""Retag a freshly built ``py3-none-any`` wheel as a platform wheel.

This package is a ctypes binding, NOT a CPython C-extension: the bundled
``libsasso`` has no Python-ABI linkage, so ONE native library per ``(OS, arch)``
serves every CPython 3.x. We therefore build a single wheel per target and tag
it ``py3-none-<platform>`` (e.g. ``py3-none-macosx_11_0_arm64``,
``py3-none-manylinux_2_17_x86_64``, ``py3-none-win_amd64``), rather than
cibuildwheel's per-Python matrix.

This wraps ``python -m wheel tags`` to (1) set ``--python-tag py3 --abi-tag none``
and the given ``--platform-tag``, removing the original tag, and (2) flip the
wheel's ``Root-Is-Purelib`` flag to ``false`` so installers treat the wheel as
platlib (it carries a compiled artifact). Run AFTER the per-platform wheel-repair
step (delocate / auditwheel / delvewheel).

    python scripts/retag_wheel.py --platform-tag macosx_11_0_arm64 \
        --in-dir wheelhouse --out-dir wheelhouse
"""
from __future__ import annotations

import argparse
import glob
import subprocess
import sys
import zipfile
from pathlib import Path


def _set_platlib(wheel_path: Path) -> None:
    """Rewrite ``Root-Is-Purelib: true`` -> ``false`` in the wheel's WHEEL file.

    hatchling marks a wheel of pure-Python source as purelib even when we bundle
    a native lib; a platform wheel must be platlib. We rewrite the one metadata
    line in place (the rest of the archive is copied verbatim).
    """
    tmp = wheel_path.with_suffix(".whl.tmp")
    with zipfile.ZipFile(wheel_path, "r") as zin:
        names = zin.namelist()
        wheel_meta_name = next(n for n in names if n.endswith(".dist-info/WHEEL"))
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                data = zin.read(info.filename)
                if info.filename == wheel_meta_name:
                    text = data.decode("utf-8")
                    text = text.replace(
                        "Root-Is-Purelib: true", "Root-Is-Purelib: false"
                    )
                    data = text.encode("utf-8")
                zout.writestr(info, data)
    tmp.replace(wheel_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform-tag", required=True, help="e.g. macosx_11_0_arm64")
    parser.add_argument("--in-dir", default="wheelhouse", help="dir holding the input wheel")
    parser.add_argument("--out-dir", default="wheelhouse", help="dir for the retagged wheel")
    args = parser.parse_args()

    in_dir = Path(args.in_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    candidates = sorted(glob.glob(str(in_dir / "*-py3-none-any.whl")))
    if not candidates:
        candidates = sorted(glob.glob(str(in_dir / "*.whl")))
    if len(candidates) != 1:
        raise SystemExit(
            f"expected exactly one input wheel in {in_dir}, found: {candidates}"
        )
    src_wheel = candidates[0]

    cmd = [
        sys.executable,
        "-m",
        "wheel",
        "tags",
        "--python-tag",
        "py3",
        "--abi-tag",
        "none",
        "--platform-tag",
        args.platform_tag,
        "--remove",
        src_wheel,
    ]
    print("+", " ".join(cmd), flush=True)
    # `wheel tags` writes the retagged wheel next to the input and prints its name.
    out_name = subprocess.run(
        cmd, check=True, capture_output=True, text=True
    ).stdout.strip().splitlines()[-1]

    produced = Path(src_wheel).parent / out_name
    final = out_dir / out_name
    if produced.resolve() != final.resolve():
        produced.replace(final)

    _set_platlib(final)
    print(f"retagged -> {final} (Root-Is-Purelib: false)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
