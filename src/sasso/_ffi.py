"""Private ctypes plumbing for the libsasso C ABI.

NOTHING in here is part of the public API — import from ``sasso`` instead. This
module owns every ``ctypes`` detail: struct layouts mirroring ``sasso.h``, the
CDLL handle, the importer-callback trampolines, and the sink dispatch. The
public ``sasso.compile`` / ``sasso.Importer`` surface is built on top of it in
``__init__.py`` so that a user never sees a ``ctypes`` type.

The struct layouts below mirror ``native/include/sasso.h`` exactly. They are
locked to the C ABI of the vendored ``native/src/lib.rs`` (core ``sasso 0.6.0``);
a change to either must be made in lockstep with the other.
"""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Locating the bundled native library.
#
# The lib ships *inside* the package (as package data), so we resolve it relative
# to this file — never an absolute machine path. Each platform wheel bundles the
# single shared library for its (OS, arch): libsasso.so (Linux), libsasso.dylib
# (macOS), or sasso.dll (Windows). We probe the names valid for the running
# platform so the loader works whichever wheel got installed.
# ---------------------------------------------------------------------------
_LIB_NAMES = {
    "darwin": ["libsasso.dylib"],
    "win32": ["sasso.dll"],
}.get(sys.platform, ["libsasso.so", "libsasso.dylib"])


def _find_library() -> str:
    here = Path(__file__).resolve().parent
    for name in _LIB_NAMES:
        candidate = here / name
        if candidate.exists():
            return str(candidate)
    raise ImportError(
        "could not find the bundled libsasso shared library next to "
        f"{here!r} (looked for {_LIB_NAMES}). This sasso wheel may be for a "
        "different platform than the one you're running on."
    )


# ABI constants (mirror sasso.h).
STYLE_EXPANDED = 0
STYLE_COMPRESSED = 1

SYNTAX_SCSS = 0
SYNTAX_SASS = 1
SYNTAX_CSS = 2

IMPORTER_OK = 1
IMPORTER_NOT_FOUND = 0
IMPORTER_ERROR = -1


# --- struct layouts (mirror sasso.h exactly) ------------------------------
class SassoCanonicalizeContext(ctypes.Structure):
    _fields_ = [
        ("from_import", ctypes.c_int32),
        ("containing_url", ctypes.c_char_p),
    ]


# canonicalize(user_data, url, ctx*, sink) -> int32
CANONICALIZE_FN = ctypes.CFUNCTYPE(
    ctypes.c_int32,
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.POINTER(SassoCanonicalizeContext),
    ctypes.c_void_p,
)
# load(user_data, canonical, sink) -> int32
LOAD_FN = ctypes.CFUNCTYPE(
    ctypes.c_int32,
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_void_p,
)


class SassoImporter(ctypes.Structure):
    _fields_ = [
        ("user_data", ctypes.c_void_p),
        ("canonicalize", CANONICALIZE_FN),
        ("load", LOAD_FN),
    ]


class SassoOptions(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("style", ctypes.c_int32),
        ("syntax", ctypes.c_int32),
        ("unicode", ctypes.c_int32),
        ("url", ctypes.c_char_p),
        ("load_paths", ctypes.POINTER(ctypes.c_char_p)),
        ("load_paths_len", ctypes.c_size_t),
        ("importer", ctypes.POINTER(SassoImporter)),
    ]


class SassoResult(ctypes.Structure):
    _fields_ = [
        ("ok", ctypes.c_int32),
        ("css", ctypes.c_void_p),
        ("css_len", ctypes.c_size_t),
        ("error", ctypes.c_void_p),
        ("error_len", ctypes.c_size_t),
        ("error_line", ctypes.c_uint32),
        ("error_column", ctypes.c_uint32),
    ]


# --- load the lib and declare signatures ----------------------------------
_lib = ctypes.CDLL(_find_library())

_lib.sasso_version.restype = ctypes.c_char_p
_lib.sasso_version.argtypes = []

_lib.sasso_options_init.restype = None
_lib.sasso_options_init.argtypes = [ctypes.POINTER(SassoOptions), ctypes.c_size_t]

_lib.sasso_compile.restype = ctypes.POINTER(SassoResult)
_lib.sasso_compile.argtypes = [
    ctypes.c_char_p,
    ctypes.c_size_t,
    ctypes.POINTER(SassoOptions),
]

_lib.sasso_result_free.restype = None
_lib.sasso_result_free.argtypes = [ctypes.POINTER(SassoResult)]

_lib.sasso_importer_set_canonical.restype = None
_lib.sasso_importer_set_canonical.argtypes = [
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_size_t,
]

_lib.sasso_importer_set_result.restype = None
_lib.sasso_importer_set_result.argtypes = [
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_size_t,
    ctypes.c_int32,
    ctypes.c_char_p,
    ctypes.c_size_t,
]

_lib.sasso_importer_set_error.restype = None
_lib.sasso_importer_set_error.argtypes = [
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_size_t,
]


def version() -> str:
    """Version of the bundled native compiler, from ``sasso_version()``."""
    return _lib.sasso_version().decode("utf-8")
