# sasso

[![PyPI](https://img.shields.io/pypi/v/sasso.svg)](https://pypi.org/project/sasso/)

Python bindings for [**sasso**](https://github.com/momiji-rs/sasso) — a fast,
pure-Rust SCSS/Sass → CSS compiler — over its `libsasso` C ABI.

`sasso` runs **in-process** (no Node, no subprocess, no system `sass` binary)
via a small `ctypes` layer over a prebuilt native library. Each wheel bundles
the compiled `libsasso` for its platform, so `pip install sasso` is all you
need.

```bash
pip install sasso
```

## Usage

```python
import sasso

css = sasso.compile(
    """
    $brand: #336699;
    .card {
        color: $brand;
        .title { font-weight: bold; }
    }
    """
)
print(css)
```

```python
# Compressed output, .sass (indented) syntax, filesystem load paths:
sasso.compile(src, style="compressed")
sasso.compile(indented_src, syntax="sass")
sasso.compile(src, load_paths=["styles", "vendor"])
```

### Errors

A compile failure raises `sasso.SassoError`, carrying the diagnostic message
plus the 1-based source location:

```python
try:
    sasso.compile(".broken { color: ; }")
except sasso.SassoError as e:
    print(e.message, e.line, e.column)
```

### Custom importers

Resolve `@use` / `@forward` / `@import` yourself (from a database, a bundler's
virtual filesystem, HTTP, …) by subclassing `sasso.Importer`. It mirrors
dart-sass's two-phase model:

```python
class DictImporter(sasso.Importer):
    def __init__(self, files):
        self.files = files

    def canonicalize(self, url, *, from_import, containing_url):
        # Map a (possibly relative) URL to a stable canonical key, or None.
        return url if url in self.files else None

    def load(self, canonical):
        # Fetch the source for a canonical key, or None.
        return sasso.LoadResult(contents=self.files[canonical], syntax="scss")

css = sasso.compile('@use "theme";', importer=DictImporter({"theme": "$c: red;"}))
```

An exception raised inside an importer aborts the compile and surfaces as a
`SassoError` with the original exception chained as `__cause__`.

## API

| Symbol | Description |
| --- | --- |
| `compile(source, *, style="expanded", syntax="scss", load_paths=None, url=None, importer=None) -> str` | Compile a stylesheet string to CSS. |
| `SassoError` | Raised on failure; has `.message: str`, `.line: int \| None`, `.column: int \| None`. |
| `Importer` | ABC for custom resolution: `canonicalize(url, *, from_import, containing_url)` + `load(canonical) -> LoadResult \| None`. |
| `LoadResult(contents, syntax="scss", source_map_url=None)` | Return value of `Importer.load`. |
| `compiler_version() -> str` | Version of the bundled native `sasso` compiler. |
| `__version__` | Version of this Python package (independent of the compiler version). |

`style` is `"expanded"` or `"compressed"`; `syntax` is `"scss"`, `"sass"`, or
`"css"`.

## Performance

`sasso` compiles in-process, so it avoids the per-call process-spawn overhead of
shelling out to the `sass` CLI. Compiling a non-trivial stylesheet 200× on an
Apple-silicon Mac (`benchmark.py`, vs. spawning the dart-sass binary per
compile):

```
output parity (sasso vs dart-sass): IDENTICAL

  sasso (in-process)        :   0.0068 s total  (0.034 ms/compile)
  dart-sass (subprocess/ea) :   4.7381 s total  (23.691 ms/compile)

  speedup: sasso is 701.0x faster for 200 compiles in this workload
```

Most of that gap is process-startup cost that an in-process binding removes
entirely; the comparison reflects the realistic "shell out to `sass`" path a
Python app would otherwise take.

## Versioning — which compiler is bundled?

The **package** version (`sasso.__version__`) floats independently of the
**compiler** version it bundles (`sasso.compiler_version()`):

| sasso (PyPI) | bundles core `sasso` crate |
| --- | --- |
| 0.1.0 | 0.6.0 |

Each release notes its bundled core version in the [CHANGELOG](CHANGELOG.md).

## How it works

The package is a `ctypes` binding — **not** a CPython C-extension — over the
[`libsasso` C ABI](https://github.com/momiji-rs/sasso/tree/master/ffi). Because
it has no Python-ABI linkage, a single native library per `(OS, arch)` serves
every CPython 3.x (and PyPy), so each release ships one platform wheel per
target rather than one per Python version.

The native crate is vendored from `momiji-rs/sasso` `ffi/` and builds against
the **published** `sasso` crate from crates.io.

## License

MIT OR Apache-2.0, at your option. See [LICENSE-MIT](LICENSE-MIT) and
[LICENSE-APACHE](LICENSE-APACHE).
