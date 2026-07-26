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

Turns a coverage percentage (e.g. from `tarpaulin`) into something useful, all
self-hosted on an S3/R2 bucket: a shields-style **SVG badge**, a per-PR **comment**
with the delta vs the default branch, and an optional **ratchet** gate (a PR can't drop
coverage below the baseline minus a tolerance). The baseline lives in the bucket — the
default branch writes it, PRs read it.

```yaml
- id: cov
  uses: cestef/actions/tarpaulin@github
  with: { out: "Stdout Xml" }
- uses: cestef/actions/coverage-report@github
  with:
    percent: ${{ steps.cov.outputs.percent }}
    bucket: my-badges              # a public bucket, for the badge URL
    endpoint: ${{ secrets.R2_ENDPOINT }}
    access-key-id: ${{ secrets.R2_BADGE_ACCESS_KEY_ID }}
    secret-access-key: ${{ secrets.R2_BADGE_SECRET_ACCESS_KEY }}
    public-url: https://<id>.r2.dev          # where the bucket is served
    token: ${{ secrets.GITHUB_TOKEN }}       # for the PR comment (pull-requests: write)
    server-url: ${{ github.api_url }}
    repo: ${{ github.repository }}
    event-name: ${{ github.event_name }}
    ref-name: ${{ github.ref_name }}
    pr-number: ${{ github.event.pull_request.number }}
    ratchet: "true"
```

Badge: `![coverage](https://<id>.r2.dev/coverage.svg)`. The bucket needs write access
scoped to the token you pass (a public R2 bucket with `wrangler r2 bucket dev-url enable`).

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
restores. `coverage-report` still writes its badge and baseline to an S3/R2 bucket, since
a badge needs public hosting; treat that bucket as trusted.

## License

MIT.
