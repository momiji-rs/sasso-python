"""sasso — a pure-Rust SCSS → CSS compiler, with a clean Pythonic API.

    import sasso

    css = sasso.compile(".a { .b { color: red; } }")

No ctypes leaks into anything you touch here; all the FFI plumbing lives in the
private :mod:`sasso._ffi` module, over the ``libsasso`` C ABI.

``__version__`` is the version of THIS Python package; the bundled compiler's
version is reported separately by :func:`compiler_version`.
"""
from __future__ import annotations

import ctypes
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Sequence

from . import _ffi

__all__ = [
    "compile",
    "SassoError",
    "Importer",
    "LoadResult",
    "compiler_version",
    "__version__",
]

#: Version of this Python package (PEP 396). Floats independently of the bundled
#: ``sasso`` compiler crate, whose version is :func:`compiler_version`. This is
#: the single source of truth: ``pyproject.toml`` reads it dynamically.
__version__ = "0.1.1"


def compiler_version() -> str:
    """Return the version of the bundled native ``sasso`` compiler.

    This is the version of the Rust ``sasso`` crate the wheel was built against
    (e.g. ``"0.6.0"``), reported by the native library's ``sasso_version()``. It
    is distinct from :data:`__version__`, which is the version of this Python
    package.
    """
    return _ffi.version()


class SassoError(Exception):
    """Raised when a compile fails (syntax error, missing import, an importer
    raising, etc.).

    Attributes
    ----------
    message : str
        The full diagnostic message from the compiler.
    line : int | None
        1-based line of the error, or ``None`` if the compiler didn't locate it.
    column : int | None
        1-based column of the error, or ``None`` if unknown.
    """

    def __init__(
        self,
        message: str,
        line: Optional[int] = None,
        column: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.message: str = message
        self.line: Optional[int] = line
        self.column: Optional[int] = column

    def __str__(self) -> str:
        if self.line is not None:
            loc = f"{self.line}:{self.column}" if self.column is not None else str(self.line)
            return f"{self.message} (at {loc})"
        return self.message


@dataclass
class LoadResult:
    """What an :meth:`Importer.load` returns: the stylesheet source plus how to
    parse it.

    Attributes
    ----------
    contents : str
        The stylesheet source text.
    syntax : "scss" | "sass" | "css"
        How to parse ``contents``. Default ``"scss"``.
    source_map_url : str | None
        Optional source-map URL override for this loaded file.
    """

    contents: str
    syntax: str = "scss"  # "scss" | "sass" | "css"
    source_map_url: Optional[str] = None


class Importer(ABC):
    """Subclass this to resolve ``@use`` / ``@forward`` / ``@import`` yourself
    (e.g. from a database, a bundler's virtual filesystem, or HTTP).

    Two phases, mirroring dart-sass:

    * :meth:`canonicalize` turns a possibly-relative, extension-less URL into a
      stable canonical key (or returns ``None`` if this importer doesn't handle
      it).
    * :meth:`load` fetches the source for a canonical key.

    Raising any exception inside either method aborts the compile and surfaces
    as a :class:`SassoError` (the original exception is chained as ``__cause__``).
    """

    @abstractmethod
    def canonicalize(
        self,
        url: str,
        *,
        from_import: bool,
        containing_url: Optional[str],
    ) -> Optional[str]:
        """Resolve ``url`` to a canonical key, or return ``None`` if unhandled.

        ``from_import`` is ``True`` for a legacy ``@import``. ``containing_url``
        is the canonical key of the importing file (``None`` for the
        entrypoint), so you can resolve relative URLs.
        """

    @abstractmethod
    def load(self, canonical: str) -> Optional[LoadResult]:
        """Return the source for ``canonical`` (from :meth:`canonicalize`), or
        ``None`` if it can't be loaded."""


_SYNTAX = {"scss": _ffi.SYNTAX_SCSS, "sass": _ffi.SYNTAX_SASS, "css": _ffi.SYNTAX_CSS}
_STYLE = {"expanded": _ffi.STYLE_EXPANDED, "compressed": _ffi.STYLE_COMPRESSED}


class _ImporterBridge:
    """Wraps a user :class:`Importer` in the C-ABI trampolines and keeps every
    object the FFI layer points at (the ``CFUNCTYPE`` thunks, the struct) alive
    for the whole compile. Also captures the first exception raised in a callback
    so the caller can re-raise it after ``sasso_compile`` returns (we must not
    let a Python exception unwind through the C frame, which is undefined
    behavior)."""

    def __init__(self, importer: Importer) -> None:
        self._importer = importer
        self.pending_exception: Optional[BaseException] = None

        # Bind the trampolines to instance attributes => GC-rooted for the life
        # of this bridge, which the caller keeps alive across the compile.
        self._cb_canon = _ffi.CANONICALIZE_FN(self._canonicalize)
        self._cb_load = _ffi.LOAD_FN(self._load)
        self.struct = _ffi.SassoImporter(
            user_data=None,
            canonicalize=self._cb_canon,
            load=self._cb_load,
        )

    def _set_error(self, sink: int, exc: BaseException) -> int:
        if self.pending_exception is None:
            self.pending_exception = exc
        msg = str(exc).encode("utf-8")
        _ffi._lib.sasso_importer_set_error(sink, msg, len(msg))
        return _ffi.IMPORTER_ERROR

    def _canonicalize(self, _user_data, url_bytes, ctx_ptr, sink) -> int:
        try:
            url = url_bytes.decode("utf-8")
            ctx = ctx_ptr.contents
            containing = ctx.containing_url.decode("utf-8") if ctx.containing_url else None
            canon = self._importer.canonicalize(
                url,
                from_import=bool(ctx.from_import),
                containing_url=containing,
            )
            if canon is None:
                return _ffi.IMPORTER_NOT_FOUND
            b = canon.encode("utf-8")
            _ffi._lib.sasso_importer_set_canonical(sink, b, len(b))
            return _ffi.IMPORTER_OK
        except BaseException as exc:  # noqa: BLE001 — must not unwind into C
            return self._set_error(sink, exc)

    def _load(self, _user_data, canon_bytes, sink) -> int:
        try:
            canonical = canon_bytes.decode("utf-8")
            result = self._importer.load(canonical)
            if result is None:
                return _ffi.IMPORTER_NOT_FOUND
            contents = result.contents.encode("utf-8")
            syntax = _SYNTAX.get(result.syntax, _ffi.SYNTAX_SCSS)
            smu = result.source_map_url
            smu_bytes = smu.encode("utf-8") if smu else None
            smu_len = len(smu_bytes) if smu_bytes else 0
            _ffi._lib.sasso_importer_set_result(
                sink, contents, len(contents), syntax, smu_bytes, smu_len
            )
            return _ffi.IMPORTER_OK
        except BaseException as exc:  # noqa: BLE001
            return self._set_error(sink, exc)


def compile(
    source: str,
    *,
    style: str = "expanded",
    syntax: str = "scss",
    load_paths: Optional[Sequence[str]] = None,
    url: Optional[str] = None,
    importer: Optional[Importer] = None,
) -> str:
    """Compile ``source`` to a CSS string.

    Parameters
    ----------
    source : str
        The stylesheet source.
    style : "expanded" | "compressed"
        Output style. Default ``"expanded"``.
    syntax : "scss" | "sass" | "css"
        Syntax of ``source``. Default ``"scss"``.
    load_paths : sequence of str, optional
        Filesystem directories searched by the built-in importer for
        ``@use`` / ``@import``. Ignored when ``importer`` is given.
    url : str, optional
        Display path for the entrypoint; enables nicer error snippets and is the
        ``containing_url`` your importer sees for top-level imports.
    importer : Importer, optional
        A custom importer. Takes precedence over ``load_paths``.

    Returns
    -------
    str
        The compiled CSS.

    Raises
    ------
    SassoError
        On any compile failure. If a custom importer raised, that original
        exception is chained (``__cause__``).
    ValueError
        For an unknown ``style`` or ``syntax``.
    """
    try:
        style_code = _STYLE[style]
    except KeyError:
        raise ValueError(
            f"unknown style {style!r}; expected one of {sorted(_STYLE)}"
        ) from None
    try:
        syntax_code = _SYNTAX[syntax]
    except KeyError:
        raise ValueError(
            f"unknown syntax {syntax!r}; expected one of {sorted(_SYNTAX)}"
        ) from None

    opts = _ffi.SassoOptions()
    _ffi._lib.sasso_options_init(ctypes.byref(opts), ctypes.sizeof(opts))
    opts.style = style_code
    opts.syntax = syntax_code

    # Keep every transient buffer alive until after the compile returns.
    keepalive: List[object] = []

    if url is not None:
        url_b = url.encode("utf-8")
        keepalive.append(url_b)
        opts.url = url_b

    bridge: Optional[_ImporterBridge] = None
    if importer is not None:
        bridge = _ImporterBridge(importer)
        keepalive.append(bridge)
        opts.importer = ctypes.pointer(bridge.struct)
    elif load_paths:
        encoded = [p.encode("utf-8") for p in load_paths]
        keepalive.extend(encoded)
        arr_type = ctypes.c_char_p * len(encoded)
        arr = arr_type(*encoded)
        keepalive.append(arr)
        opts.load_paths = ctypes.cast(arr, ctypes.POINTER(ctypes.c_char_p))
        opts.load_paths_len = len(encoded)

    raw = source.encode("utf-8")
    res_ptr = _ffi._lib.sasso_compile(raw, len(raw), ctypes.byref(opts))
    if not res_ptr:
        raise SassoError("sasso_compile returned NULL (out of memory or internal panic)")
    res = res_ptr.contents
    try:
        if res.ok:
            return ctypes.string_at(res.css, res.css_len).decode("utf-8")

        # Failure. If a custom importer raised a Python exception, prefer that as
        # the chained cause.
        message = (
            ctypes.string_at(res.error, res.error_len).decode("utf-8")
            if res.error
            else "unknown compile error"
        )
        line = res.error_line or None
        column = res.error_column or None
        err = SassoError(message, line=line, column=column)
        if bridge is not None and bridge.pending_exception is not None:
            raise err from bridge.pending_exception
        raise err
    finally:
        _ffi._lib.sasso_result_free(res_ptr)
        # `keepalive` is held until here, after the C call has fully returned.
        del keepalive
