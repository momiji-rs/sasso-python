# Releasing `sasso-python`

Wheels are published to [PyPI](https://pypi.org/project/sasso/) via **Trusted
Publishing (OIDC, no API token)** by `.github/workflows/release.yml`.

## Cut a release

1. Bump `__version__` in `src/sasso/__init__.py` and add a `CHANGELOG.md` entry.
   The package version floats independently of the bundled compiler; note which
   core it pins (`native/Cargo.toml` → `sasso_core = "=X.Y.Z"`).
2. Commit, then tag and push:
   ```console
   $ git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z
   ```
   The tag triggers the full matrix → build every wheel + the sdist → publish.
   The `sdist` job asserts `__version__` equals the tag (`v` + version).

**Dry run (no publish):** trigger the workflow manually (`workflow_dispatch`,
e.g. `gh workflow run "Release (PyPI)"`). It builds the entire wheel matrix as
artifacts and **stops before publishing** (the `publish` job is gated to tag
pushes). Use this to validate a new platform before cutting a tag.

## One-time PyPI setup

Register a Trusted Publisher (pending publisher, before the first release) at
pypi.org → Account → Publishing: **project** `sasso`, **owner** `momiji-rs`,
**repo** `sasso-python`, **workflow** `release.yml`, **environment** `release`.
Add a `release` environment in the repo settings too.

## How the wheels are built (and why)

`sasso` is a **`ctypes` binding, not a CPython C-extension** — the bundled
`libsasso` has no Python-ABI linkage, so **one native library per `(OS, arch)`
serves every CPython 3.x**. We therefore build a single wheel per target tagged
`py3-none-<platform>` (no per-Python matrix, no `cibuildwheel`). Each job:

1. `scripts/build_native.py` builds the vendored `native/` cdylib (against the
   **published** `sasso` crate) and copies `libsasso.{so,dylib}` / `sasso.dll`
   into `src/sasso/`.
2. `python -m build --wheel` produces a `py3-none-any` wheel.
3. The platform-specific repair tool vendors deps + verifies the baseline:
   `auditwheel` (Linux), `delocate` (macOS), `delvewheel` (Windows).
4. `scripts/retag_wheel.py` rewrites the tag to `py3-none-<platform>` and flips
   the wheel to `Root-Is-Purelib: false` (it carries a compiled artifact).

### Per-platform notes / gotchas (learned the hard way)

- **`wheel` must be installed in every wheel job.** `retag_wheel.py` shells out
  to `python -m wheel tags`; `build` + the repair tool do not pull `wheel` in.
- **Linux** builds run *inside* the official PyPA containers (rustup is installed
  in-container; the images have no rust). The glibc image is
  `quay.io/pypa/manylinux2014_<arch>` — **`manylinux_2_17_<arch>` is not a
  published image name** (quay returns "unauthorized"), though it *is* the
  auditwheel policy name. **aarch64** is cross-built by running the aarch64
  container under **QEMU** binfmt emulation — correct, but slow (~15–20 min for
  the emulated `cargo build`).
- **musllinux** (Alpine) needs **`RUSTFLAGS=-C target-feature=-crt-static`**:
  the musl target defaults to a *static* C runtime, which can't produce a
  cdylib (`error: cannot produce cdylib for x86_64-unknown-linux-musl`); the flag
  links musl dynamically so a `.so` can be built.
- **macOS** builds **both arches on the `macos-14` (arm64) runner**; the x86_64
  dylib is **cross-compiled** (`cargo --target x86_64-apple-darwin`, with the
  target added via `dtolnay/rust-toolchain`'s `targets:`). `delocate` inspects
  and repairs the cross-built dylib without executing it. We deliberately do
  **not** use the `macos-13` (Intel) runner — its pool queues unreliably (45+ min
  observed) and would block the whole release (`publish` needs every job).
- **`sdist`** carries the vendored `native/` crate but **no prebuilt library**
  (a CI assertion enforces this); installing from sdist requires a Rust toolchain.
- **Action versions** are kept on the Node-24 majors (`actions/checkout@v6`,
  `actions/upload-artifact@v7`, `actions/download-artifact@v8`,
  `actions/setup-python@v6`, `docker/setup-qemu-action@v4`).

### Local cross-compile caveat

`cargo build --target <triple>` may fail locally with `E0463 (can't find crate
for std)` if Homebrew's `rustc`/`cargo` shadow rustup (the rustup-added target's
std isn't seen). CI uses a clean rustup toolchain, where it works.
