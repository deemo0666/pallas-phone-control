# Pallas Phone Control

English | [简体中文](README.zh-CN.md)

Phone Control is an optional plugin for [Pallas Agent](https://github.com/deemo0666/pallas-agent). It lets the AI operate other apps on your iPhone or iPad. Setup runs entirely on the device itself — no computer needed.

## Requirements

- iOS or iPadOS 27 or later (pairing from the device itself arrived in iOS 27).
- Pallas Agent with the on-device engine and its built-in Linux shell.
- A free Apple ID (used to sign the on-device runner; it is entered only on the signing page, never in chat).
- Internet access to Apple during setup and renewal.

## Install the plugin

Switch Pallas to the on-device engine, then use either option:

- **Plugin market:** open **Settings → Capabilities → Plugins → Plugin Market**, search for "Phone Control", and tap Install.
- **Offline package:** save `pallasboot-runner.zip` to the Files app, then open **Settings → Capabilities → Plugins**, tap **Add Plugin → Choose File or Folder**, pick the ZIP, and tap **Import and Enable**.

If you have an older version installed (including the old `pallas-siboot-probe` package), uninstall it from the plugin details page first. Your signing state and renewal schedule are kept outside the plugin folder and survive the uninstall.

## Set it up

In an on-device chat, say **"Set up phone control"**. The agent checks what is already done, skips those steps, and guides you through the rest one step at a time. The first time, you will be asked to:

1. Allow iOS to add the **PallasBoot** VPN configuration (a local tunnel to the device itself; traffic does not leave the phone).
2. Allow **Local Network** access.
3. Sign in with your Apple ID on the on-device signing page.
4. Open **Settings → Privacy & Security → Developer Mode → Other Devices**, tap **Pair with PallasBoot**, and enter your passcode and the six-digit code shown on the status page.
5. Turn on the switch under **Settings → Phone Control** in Pallas.

When setup finishes, the agent verifies it by opening Calculator and computing 37 × 19 (expected: 703), then tells you when the component expires and whether auto-renewal is on. You can also test it any time with **Settings → Phone Control → Try Phone Control**.

### If Developer Mode is missing from Settings

Tell the agent; it runs `setup.sh reveal`. You will be asked to open a link in Safari, install a small "identify this device" profile (it only reports the device UDID, model and OS version, and leaves no settings behind), and then tap Install on a signing page. After that, **Developer Mode** appears under **Settings → Privacy & Security**. Turn it on, restart, and return to Pallas to continue setup.

### Certificate limit (Apple error 7460)

Your Apple ID has reached its development-certificate limit. The signing page lets you either keep your existing certificates and exit, or revoke one. Revoking a certificate affects other apps signed with it.

## Auto-renewal

Apps signed with a free Apple ID expire after 7 days. After a successful install, auto-renewal is on by default: Pallas checks at launch and every 15 minutes, and renews within 48 hours of expiry (retrying at most once an hour on failure). If iPadOS or iOS suspends Pallas, checks resume the next time you open it.

Renewal reuses the same device pairing, Apple session and certificate. If the pairing is lost, the Apple session expires or the certificate is no longer valid, say "Set up phone control" again.

## Commands

The agent normally runs these for you. Replace the version in the path if yours differs.

```sh
sh /root/workspace/pallasboot-runner-0.7.3/setup.sh status        # current state and next step
sh /root/workspace/pallasboot-runner-0.7.3/setup.sh start [--new-login]   # start signing; --new-login switches Apple ID
sh /root/workspace/pallasboot-runner-0.7.3/setup.sh wait [seconds]
sh /root/workspace/pallasboot-runner-0.7.3/setup.sh reveal        # make Developer Mode appear
sh /root/workspace/pallasboot-runner-0.7.3/renew.sh status        # also: enable | disable | now
```

If `start` reports `full_access`, choose **Full Access** for the current chat under **Settings → Permissions**, retry, then switch it back.

## Privacy and security

- The status page and the signer listen only on loopback addresses on the device.
- Pairing records, the Apple session and signing keys are stored in `/root/.pallasboot` (mode 0700) on the on-device Linux disk.
- The signer verifies the bundled runner's fixed SHA-256 and the provisioning profile before installing, and revokes a certificate only after you choose it and confirm.

## Source and licenses

The signer is based on [siboot](https://github.com/FrizzleM/siboot/tree/4ae7ef873490ee6ca7b9111e5ad2cf4fc0cb664d/minis) (MIT), with idevice and isideload (MIT) and apple-codesign-quick (LGPL-2.1-or-later). Patches, runner sources and build scripts are in `fork/`; `runner.sha256` lists the checksums of the device-side files. See [LICENSE.md](LICENSE.md) and [licenses/THIRD-PARTY.md](licenses/THIRD-PARTY.md).
