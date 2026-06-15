# Changelog

All notable changes to the **sasso** Python package are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

The package version floats independently of the `sasso` compiler crate; each
release notes the exact core crate version it bundles.

## [Unreleased]

## [0.1.0] - 2026-06-15

Initial release. In-process SCSS/Sass → CSS via a `ctypes` binding over the
`libsasso` C ABI, bundling the `sasso` compiler crate **v0.6.0**.

### Added

- `sasso.compile(source, *, style="expanded", syntax="scss", load_paths=None,
  url=None, importer=None) -> str` — compile a stylesheet string to CSS.
- `sasso.SassoError` carrying `.message`, `.line`, and `.column`.
- `sasso.Importer` (ABC) for custom `@use`/`@forward`/`@import` resolution, with
  dart-sass-style two-phase `canonicalize(...)` + `load(...) -> LoadResult`.
  Exceptions raised inside an importer surface as `SassoError` with the original
  chained as `__cause__`.
- `sasso.LoadResult(contents, syntax="scss", source_map_url=None)`.
- `sasso.compiler_version()` (the bundled compiler version) and a PEP 561
  `py.typed` marker (the package is fully type-hinted).
- Prebuilt platform wheels for Linux (manylinux + musllinux, x86_64 + aarch64),
  macOS (arm64 + x86_64), and Windows (x86_64). A single native library per
  `(OS, arch)` serves every CPython 3.x — this is a ctypes binding, not a
  CPython C-extension — plus a buildable-from-source sdist.
