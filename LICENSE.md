# Pallas Phone Control Plugin License

Copyright © 2026 deemo0666. All rights reserved.

A Chinese translation is in [LICENSE.zh-CN.md](LICENSE.zh-CN.md). If the two differ, this English version governs.

## Scope

This license covers the plugin source code, documentation, brand assets and plugin packages that deemo0666 owns the copyright to and provides with this license, including the Pallas iPhone Runner (`ScreenRunner.ipa`) and deemo0666's changes and additions to the signer (`fork/`). Third-party material and releases validly licensed under other terms are each governed by their own licenses.

## Reviewing the source

Anyone may download, read and review the source in this repository. Compiling, modifying, reusing or redistributing the source or derivative works requires written permission from the copyright holder, unless this license, another valid license, applicable law or the hosting platform's terms allow it.

## Official plugin package

Anyone who obtains the official plugin package (from npm, the Pallas Agent plugin market or this repository's releases) may install it into Pallas Agent or DSH on devices they own or manage and use it as described in the included instructions. Sublicensing, redistributing the plugin package or otherwise using the Pallas brand assets requires written permission from the copyright holder, unless another valid license or applicable law allows it.

## Third-party components

The signer `siboot-runner-aarch64` is built from third-party source listed in `licenses/THIRD-PARTY.md`, each governed by its original license. It statically links apple-codesign-quick, licensed under the LGPL 2.1 or later (`licenses/LGPL-2.1.txt`). As that license requires, you may modify the signer for your own use and rebuild and relink it with a modified version of that library, using the source and build script in `fork/`, and reverse-engineer it to debug such modifications. Nothing in this license restricts the rights the LGPL gives you for that library.
