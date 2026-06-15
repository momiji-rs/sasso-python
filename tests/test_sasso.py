"""pytest suite for the `sasso` Python package.

Run against an INSTALLED wheel (so the bundled native lib is exercised exactly
as a user would get it), ideally from a venv created outside the source tree:

    python -m pytest tests/ -v
"""
from __future__ import annotations

import pytest

import sasso


# --- version surface -------------------------------------------------------
def test_package_version_is_independent():
    # The PACKAGE version (this Python distribution) floats independently of the
    # bundled compiler; it is a plain semver string, not the compiler version.
    assert sasso.__version__ == "0.1.0"


def test_compiler_version_is_bundled_core():
    # compiler_version() reports the native sasso crate the wheel was built
    # against. This release bundles core 0.6.0.
    assert sasso.compiler_version() == "0.6.0"
    assert sasso.compiler_version() != sasso.__version__


# --- basic compile ---------------------------------------------------------
def test_compile_expanded_nesting_and_variables():
    css = sasso.compile(
        "$brand: #336699;\n.card { color: $brand; .title { font-weight: bold; } }"
    )
    assert ".card {" in css
    assert "color: #336699;" in css
    assert ".card .title {" in css


def test_compile_compressed():
    css = sasso.compile(".a { color: red; b { x: 1; } }", style="compressed")
    assert css.startswith(".a{color:red}")
    assert ".a b{x:1}" in css


def test_compile_empty_source():
    assert sasso.compile("") == ""


# --- options ---------------------------------------------------------------
def test_syntax_sass_indented():
    src = ".a\n  color: red\n"
    css = sasso.compile(src, syntax="sass")
    assert ".a {" in css
    assert "color: red;" in css


def test_syntax_css_passthrough():
    css = sasso.compile(".a { color: red; }", syntax="css")
    assert "color: red;" in css


def test_unknown_style_raises_valueerror():
    with pytest.raises(ValueError):
        sasso.compile(".a { b: c; }", style="nope")


def test_unknown_syntax_raises_valueerror():
    with pytest.raises(ValueError):
        sasso.compile(".a { b: c; }", syntax="nope")


def test_load_paths(tmp_path):
    (tmp_path / "_partial.scss").write_text("$c: #336699;\n", encoding="utf-8")
    css = sasso.compile(
        '@use "partial" as p;\n.x { color: p.$c; }\n',
        load_paths=[str(tmp_path)],
    )
    assert "color: #336699;" in css


# --- errors ----------------------------------------------------------------
def test_compile_error_is_sasso_error_with_location():
    with pytest.raises(sasso.SassoError) as ei:
        sasso.compile(".broken { color: ; }")  # missing value
    err = ei.value
    assert isinstance(err.message, str) and err.message
    assert err.line is not None and err.line >= 1
    assert err.column is not None and err.column >= 1
    # __str__ includes the location.
    assert f"at {err.line}:{err.column}" in str(err)


# --- custom importer -------------------------------------------------------
class DictImporter(sasso.Importer):
    """Resolves URLs against an in-memory {canonical: source} map, with
    directory-relative resolution + dart's `_partial` fallback."""

    def __init__(self, files):
        self.files = files

    def canonicalize(self, url, *, from_import, containing_url):
        base = ""
        if containing_url:
            i = containing_url.rfind("/")
            base = containing_url[:i] if i > 0 else ""
        joined = base.rstrip("/") + "/" + url
        i = joined.rfind("/")
        partial = joined[: i + 1] + "_" + joined[i + 1 :]
        for cand in (joined, partial):
            if cand in self.files:
                return cand
        return None

    def load(self, canonical):
        src = self.files.get(canonical)
        if src is None:
            return None
        return sasso.LoadResult(contents=src, syntax="scss")


def test_custom_importer_relative_use():
    files = {
        "/sub/_mod": '@use "dep" as d;\n$c: d.$x;\n',
        "/sub/_dep": "$x: #336699;\n",
    }
    css = sasso.compile(
        '@use "sub/mod" as m;\n.out { color: m.$c; }\n',
        url="/entry",
        importer=DictImporter(files),
    )
    assert css == ".out {\n  color: #336699;\n}\n"


def test_importer_not_found_surfaces_as_error():
    css_files = {}

    with pytest.raises(sasso.SassoError):
        sasso.compile('@use "missing";\n', importer=DictImporter(css_files))


def test_importer_raising_chains_as_cause():
    class BoomImporter(sasso.Importer):
        def canonicalize(self, url, *, from_import, containing_url):
            raise RuntimeError("database is down")

        def load(self, canonical):
            return None

    with pytest.raises(sasso.SassoError) as ei:
        sasso.compile('@use "anything";\n', importer=BoomImporter())
    cause = ei.value.__cause__
    assert isinstance(cause, RuntimeError)
    assert "database is down" in str(cause)


def test_importer_takes_precedence_over_load_paths(tmp_path):
    # When both are given, the custom importer is used.
    (tmp_path / "_disk.scss").write_text("$c: red;\n", encoding="utf-8")
    files = {"/v/_virt": "$c: #336699;\n"}

    css = sasso.compile(
        '@use "virt" as v;\n.x { color: v.$c; }\n',
        url="/v/entry",
        load_paths=[str(tmp_path)],
        importer=DictImporter(files),
    )
    assert "color: #336699;" in css
