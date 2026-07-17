# cstef/actions

Reusable composite actions for Forgejo/Gitea Actions (Codeberg), aimed at Rust CI on
mixed arm64/amd64 runners. Each action is multiplatform (detects the runner arch),
idempotent (skips install when the tool is already present, so a prebaked runner image
pays nothing), and downloads prebuilt binaries directly (no `apt`, no GitHub-token
dependency that trips up non-GitHub forges).

Reference them by full URL and subpath:

```yaml
- uses: https://codeberg.org/cstef/actions/rust@main
- uses: https://codeberg.org/cstef/actions/mold@main
- uses: https://codeberg.org/cstef/actions/sccache@main
- uses: https://codeberg.org/cstef/actions/nextest@main
```

Pin `@main` to a tag or commit for reproducibility.

## rust

Installs `rustup` (if missing) and a toolchain, plus optional targets and components.

```yaml
- uses: https://codeberg.org/cstef/actions/rust@main
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
- uses: https://codeberg.org/cstef/actions/mold@main
  with:
    version: "2.41.0"
    rustflags: "true"          # false if you set RUSTFLAGS yourself (see note)
```

Note: a job-level `env: RUSTFLAGS` overrides anything written to `$GITHUB_ENV`. If you
need other flags too (e.g. `-D warnings`), set `rustflags: false` and put the full value
in your workflow `env:` including `-C link-arg=-fuse-ld=mold`.

## sccache

Installs [sccache](https://github.com/mozilla/sccache) and points it at an
S3-compatible bucket, exporting `RUSTC_WRAPPER=sccache` and the backend env for every
later step. Built for Cloudflare R2 but works with any S3 endpoint.

```yaml
- uses: https://codeberg.org/cstef/actions/sccache@main
  with:
    bucket: my-sccache
    endpoint: ${{ secrets.R2_ENDPOINT }}       # https://<account>.r2.cloudflarestorage.com
    region: auto                               # R2 wants 'auto'
    access-key-id: ${{ secrets.R2_ACCESS_KEY_ID }}
    secret-access-key: ${{ secrets.R2_SECRET_ACCESS_KEY }}
    key-prefix: ""                             # optional bucket sub-prefix
```

A shared bucket persists the compile cache across ephemeral runners (whose local cache
dies with the instance) and warms the static ones. It sets `CARGO_INCREMENTAL=0`, which
sccache requires.

### R2 setup

1. Create the bucket: `wrangler r2 bucket create my-sccache`.
2. Bound cost: `wrangler r2 bucket lifecycle add my-sccache --name expire-14d --expire-days 14`.
3. Create an R2 API token (Object Read & Write, scoped to the bucket) in the dashboard;
   it yields an Access Key ID, Secret Access Key, and the S3 endpoint.
4. Store the three as repo/org Actions secrets and pass them as above.

## nextest

Installs [cargo-nextest](https://nexte.st) and, optionally, runs the suite.

```yaml
- uses: https://codeberg.org/cstef/actions/nextest@main
  with:
    version: latest
    run: "true"
    args: "--workspace --no-tests warn"
```

## musl

Installs the musl C cross toolchain (`musl-gcc`, perl, make) for static builds, via
apt or apk. Idempotent.

```yaml
- uses: https://codeberg.org/cstef/actions/musl@main
  with:
    packages: ""               # extra packages
```

## cargo-cache

Persists `~/.cargo` registry + git downloads to an S3-compatible bucket, keyed on
`Cargo.lock`. Complements sccache (which caches compiler output, not crate downloads),
so ephemeral runners stop re-fetching crates. Call it twice: `restore` before the build,
`save` after.

```yaml
- uses: https://codeberg.org/cstef/actions/cargo-cache@main   # restore (default)
  with:
    bucket: my-cargo-cache
    endpoint: ${{ secrets.R2_ENDPOINT }}
    access-key-id: ${{ secrets.R2_ACCESS_KEY_ID }}
    secret-access-key: ${{ secrets.R2_SECRET_ACCESS_KEY }}
# ... build ...
- uses: https://codeberg.org/cstef/actions/cargo-cache@main
  with:
    mode: save
    bucket: my-cargo-cache
    endpoint: ${{ secrets.R2_ENDPOINT }}
    access-key-id: ${{ secrets.R2_ACCESS_KEY_ID }}
    secret-access-key: ${{ secrets.R2_SECRET_ACCESS_KEY }}
```

Trust: anyone with bucket write access can influence what lands in `~/.cargo`, so treat
the bucket as trusted (same model as the sccache bucket). Restores reject tar members
with absolute paths or `..` traversal.

## binstall

Installs [cargo-binstall](https://github.com/cargo-bins/cargo-binstall) from a pinned
release, and optionally installs crates through it.

```yaml
- uses: https://codeberg.org/cstef/actions/binstall@main
  with:
    version: "1.21.0"
    crates: "cargo-audit cargo-deny"
```

## tarpaulin

Installs [cargo-tarpaulin](https://github.com/xd009642/tarpaulin) from a pinned release
and runs coverage. Linux only.

```yaml
- uses: https://codeberg.org/cstef/actions/tarpaulin@main
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
  uses: https://codeberg.org/cstef/actions/tarpaulin@main
  with: { out: "Stdout Xml" }
- uses: https://codeberg.org/cstef/actions/coverage-report@main
  with:
    percent: ${{ steps.cov.outputs.percent }}
    bucket: my-badges              # a public bucket, for the badge URL
    endpoint: ${{ secrets.R2_ENDPOINT }}
    access-key-id: ${{ secrets.R2_BADGE_ACCESS_KEY_ID }}
    secret-access-key: ${{ secrets.R2_BADGE_SECRET_ACCESS_KEY }}
    public-url: https://<id>.r2.dev          # where the bucket is served
    token: ${{ forge.token }}                # for the PR comment
    server-url: ${{ github.server_url }}
    repo: ${{ github.repository }}
    event-name: ${{ github.event_name }}
    ref-name: ${{ github.ref_name }}
    pr-number: ${{ github.event.pull_request.number }}
    ratchet: "true"
```

Badge: `![coverage](https://<id>.r2.dev/coverage.svg)`. The bucket needs write access
scoped to the token you pass (a public R2 bucket with `wrangler r2 bucket dev-url enable`).

## mem-diagnostics

Dumps detailed memory forensics (cgroup v2/v1 usage vs cap, peak/limit %, OOM events,
`memory.stat` breakdown, system meminfo, top-RSS processes). Run it `if: failure()` on
memory-capped runners.

```yaml
- uses: https://codeberg.org/cstef/actions/mem-diagnostics@main
  if: failure()
  with:
    processes: "true"
    top: "10"
    dmesg: "false"
```

## Security

Inputs are passed via the environment, never interpolated into the shell body (no script
injection). Binaries are fetched over TLS from pinned release versions. sccache writes its
backend env with the random-delimiter heredoc form so values can't inject extra
`GITHUB_ENV` entries. cargo-cache validates tar members before extracting into `~/.cargo`.

## License

MIT.
