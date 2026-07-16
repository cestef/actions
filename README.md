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

## License

MIT.
