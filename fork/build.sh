#!/bin/sh
# Build on ARM64 Linux with Rust, a musl C toolchain, cmake and clang
# (or on a Mac with `cargo zigbuild --target aarch64-unknown-linux-musl`).
# Uses only siboot (MIT) and upstream crates: idevice and isideload (MIT),
# apple-codesign-quick (LGPL-2.1-or-later). The SideInstaller submodule is not fetched.
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
base=$(dirname "$here")
build=$(mktemp -d)
git clone --quiet --no-checkout https://github.com/FrizzleM/siboot "$build/siboot"
cd "$build/siboot"
git checkout --quiet 4ae7ef873490ee6ca7b9111e5ad2cf4fc0cb664d
git apply "$here/runner.patch"
cp "$here/runner.rs" "$here/ddi.rs" "$here/login.rs" "$here/error_text.rs" minis/src/
cd minis
PALLAS_RUNNER_SHA256=$(sha256sum "$base/ScreenRunner.ipa" | cut -d' ' -f1)
export PALLAS_RUNNER_SHA256
cargo build --locked --release --target aarch64-unknown-linux-musl
cp target/aarch64-unknown-linux-musl/release/siboot "$base/siboot-runner-aarch64"
cd "$base"
sha256sum ScreenRunner.ipa siboot-runner-aarch64 >runner.sha256
