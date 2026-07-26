# cstef/actions

Reusable composite actions for GitHub Actions, aimed at Rust CI on mixed arm64/amd64
runners. Each action is multiplatform (detects the runner arch), idempotent (skips
install when the tool is already present, so a prebaked runner image pays nothing), and
downloads prebuilt binaries directly (no `apt`, no marketplace dependency).

This is the `github` branch. The `forgejo` branch carries the same actions for
Forgejo/Gitea (Codeberg), where they are referenced by full URL instead.

Reference them by owner, subpath and branch:

```yaml
- uses: cestef/actions/rust@github
- uses: cestef/actions/mold@github
- uses: cestef/actions/sccache@github
- uses: cestef/actions/nextest@github
```

Pin `@github` to a tag or commit for reproducibility.

## rust

Installs `rustup` (if missing) and a toolchain, plus optional targets and components.

```yaml
- uses: cestef/actions/rust@github
  with:
    toolchain: ""              # empty: honor rust-toolchain.toml, else stable
    targets: ""                # "x86_64-unknown-linux-musl aarch64-unknown-linux-gnu"
    components: ""             # "clippy rustfmt"
```

## mold

Installs the [mold](https://github.com/rui314/mold) linker from its prebuilt release
(seconds, no `apt`) and, by default, appends `-C link-arg=-fuse-ld=mold` to `RUSTFLAGS`
for later steps. Linux only (no-op elsewhere).

```yaml
- uses: cestef/actions/mold@github
  with:
    version: "2.41.0"
    rustflags: "true"          # false if you set RUSTFLAGS yourself (see note)
```

Note: a job-level `env: RUSTFLAGS` overrides anything written to `$GITHUB_ENV`. If you
need other flags too (e.g. `-D warnings`), set `rustflags: false` and put the full value
in your workflow `env:` including `-C link-arg=-fuse-ld=mold`.

## sccache

Installs [sccache](https://github.com/mozilla/sccache) and points it at the GitHub
Actions cache, exporting `RUSTC_WRAPPER=sccache` for every later step. No bucket, no
credentials, no egress bill.

```yaml
- uses: cestef/actions/sccache@github
  with:
    version: v0.16.0
    key-prefix: ""     # optional namespace; bump to invalidate everything
```

It sets `CARGO_INCREMENTAL=0`, which sccache requires. The Actions cache the compiler
objects land in is the same 10 GB per-repo store `actions/cache` uses, evicted
least-recently-used, so a busy repo shares that budget with `cargo-cache`.

sccache reads `ACTIONS_RESULTS_URL` and `ACTIONS_RUNTIME_TOKEN`, which the runner hands
to JS actions but not to `run:` steps; the action re-exports them (masking the token)
so the build steps can see them.

## nextest

Installs [cargo-nextest](https://nexte.st) and, optionally, runs the suite.

```yaml
- uses: cestef/actions/nextest@github
  with:
    version: latest
    run: "true"
    args: "--workspace --no-tests warn"
```

## musl

Installs the musl C cross toolchain (`musl-gcc`, perl, make) for static builds, via
apt or apk. Idempotent.

```yaml
- uses: cestef/actions/musl@github
  with:
    packages: ""               # extra packages
```

## cargo-cache

Persists cargo state to the GitHub Actions cache. By default it caches `~/.cargo`
registry + git downloads, keyed on `Cargo.lock` (sccache caches compiler output, not
crate downloads). Point `base`/`paths` at the workspace `target/` and it also caches
dependency rlibs, build-script outputs, and cargo's fingerprint DB, which sccache does
not. Call it twice per cache: `restore` before the build, `save` after.

```yaml
- uses: cestef/actions/cargo-cache@github   # registry, restore (default)
# also cache target/ (distinct prefix; key includes the rustc version)
- uses: cestef/actions/cargo-cache@github
  with:
    prefix: target-cache
    toolchain-key: "true"
    base: "."
    paths: target
# ... build ...
- uses: cestef/actions/cargo-cache@github   # registry, save
  with:
    mode: save
```

`base` is the dir `paths` are relative to (empty = `$HOME`). `toolchain-key: true` mixes
the rustc version into the key, since compiled artifacts are toolchain-specific. Use a
distinct `prefix` per cache (registry vs target/, and one per build flavour, e.g.
instrumented coverage builds). The OS and arch are always in the key, so a mixed
arm64/amd64 matrix does not cross-restore. Keys are immutable: a `save` on an existing
key warns and moves on, so target/ is uploaded once per `Cargo.lock` + rustc.

Caches are scoped by branch: a PR reads the base branch's entries but writes only its
own, and GitHub evicts least-recently-used past 10 GB per repository.

A cache key can be reserved once, so two jobs in the same run that would save the
*same* key race and the loser logs `Cache save failed`. Give each job its own
`prefix`, or have exactly one job save a cache the others only restore.

## binstall

Installs [cargo-binstall](https://github.com/cargo-bins/cargo-binstall) from a pinned
release, and optionally installs crates through it.

```yaml
- uses: cestef/actions/binstall@github
  with:
    version: "1.21.0"
    crates: "cargo-audit cargo-deny"
```

## tarpaulin

Installs [cargo-tarpaulin](https://github.com/xd009642/tarpaulin) from a pinned release
and runs coverage. Linux only.

```yaml
- uses: cestef/actions/tarpaulin@github
  with:
    version: "0.37.0"
    args: "--workspace --exclude-files benches/*"
    out: "Stdout Xml"          # Stdout, Xml, Html, Lcov, Json
    timeout: "300"
    fail-under: ""             # e.g. "40" to enforce a floor
```

## coverage-report

Reads a coverage report and produces four things from that one parse, so they can never
disagree: an **SVG badge**, a **job summary** table, a **pull-request comment** with the
delta and the per-file movement, and an optional **ratchet** gate (a PR may not drop
below the baseline minus a tolerance).

State lives on an orphan branch of the repo itself — no bucket, no credentials beyond the
workflow token. A default-branch push writes the badge and the baseline; pull requests
read them and never move them.

```yaml
- uses: cestef/actions/tarpaulin@github
  with: { out: "Stdout Xml" }
- uses: cestef/actions/coverage-report@github
  with:
    file: cobertura.xml            # or an lcov .info; `format` defaults to auto
    token: ${{ secrets.GITHUB_TOKEN }}
    ratchet: "true"
    badge-label: coverage
```

The job needs `permissions: { contents: write, pull-requests: write }` — `contents` to
push the badge branch, `pull-requests` to comment.

Badge: `![coverage](https://raw.githubusercontent.com/<owner>/<repo>/badges/coverage.svg)`.

### Formats

`format: auto` picks by extension: `.xml` is cobertura (tarpaulin, coverage.py, gcovr),
`.info`/`.lcov` is LCOV (llvm-cov, grcov, nyc). Both reduce to per-file line counts, so
everything downstream is format-agnostic. Adding one is a class plus a line in `SOURCES`.

### Badge styles

`badge-style: gauge` (default) makes the value half a fill bar: the colored region spans
the coverage fraction over a muted track, so the badge reads as a number *and* a shape.
`badge-style: flat` is the classic two-slab badge. Colors come from `badge-thresholds`,
a comma list of `min:color` highest-first.

### Everything else is an input

`branch` and `path-prefix` (one branch can host several projects), `badge-file` /
`state-file`, `top` (rows before the rest collapse into a `<details>`), `marker` (which
comment to update), `tolerance`, `default-branch`, `commit-message` / `commit-user` /
`commit-email`, and `summary` / `comment` / `publish` / `badge-link` to turn any surface
off. `server-url`, `raw-url` and `git-url` default to the current forge, so GitHub
Enterprise is a matter of pointing them elsewhere.

Outputs: `percent`, `delta`, `covered`, `total`.

Without a `token` it still parses, renders the badge into the runner temp dir and writes
the summary — it just cannot read a baseline, comment, or publish.

## wrangler

Runs [Wrangler](https://developers.cloudflare.com/workers/wrangler/) (deploy by default).
Modern wrangler is npm-only, so this needs Node on the runner; the official
`cloudflare/wrangler-action` is a wrapper around the same `npx wrangler` call.

```yaml
- uses: cestef/actions/wrangler@github
  with:
    version: "4.112.0"
    command: "deploy"                          # e.g. "versions upload", "d1 migrations apply"
    working-directory: "."
    api-token: ${{ secrets.CLOUDFLARE_API_TOKEN }}
    account-id: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
```

An ephemeral runner cold-downloads wrangler + the native `workerd` (tens of MB) every
job, so the pinned install is cached by default, keyed on `version + os + arch`. Set
`cache: "false"` to fall back to a plain `npx wrangler@<version>`.

## mem-diagnostics

Dumps detailed memory forensics (cgroup v2/v1 usage vs cap, peak/limit %, OOM events,
`memory.stat` breakdown, system meminfo, top-RSS processes). Run it `if: failure()` on
memory-capped runners.

```yaml
- uses: cestef/actions/mem-diagnostics@github
  if: failure()
  with:
    processes: "true"
    top: "10"
    dmesg: "false"
```

## Security

Shared shell helpers (version validation, arch detection) live in `_lib/common.sh`,
sourced by each action via `$GITHUB_ACTION_PATH/../_lib/common.sh`.

Inputs are passed via the environment, never interpolated into the shell body (no script
injection). Binaries are fetched over TLS from pinned release versions. Anything written
to `GITHUB_ENV` or `GITHUB_OUTPUT` uses the random-delimiter heredoc form, so a value
containing a newline cannot inject extra entries.

`sccache`, `cargo-cache` and `wrangler` store to the GitHub Actions cache, which is
scoped per repository and per branch: a pull request reads the base branch's entries but
writes only its own, so a fork PR cannot poison what a later default-branch build
restores. `coverage-report` pushes only to its own orphan branch, with the token in a
git header rather than the remote URL so it cannot surface in git's error output.

No action in this branch needs a cloud credential: everything persists in the GitHub
Actions cache or in the repository itself.

## License

MIT.
