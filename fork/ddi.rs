//! The Developer Disk Image the runner needs: it is an XCTest runner, and iOS 17 and later start
//! one only with the personalized developer image mounted. A device that never met Xcode has none
//! (a reset iPad, 2026-11-21: installed, trusted, and still refused to launch), and every restart
//! unmounts it. The plugin downloads the image (ddi.py, pinned hashes); this mounts it through the
//! tunnel, personalized for this device by Apple's TSS.

use crate::{
    fail::{Fail, Result},
    tunnel::Connection,
    ui,
};
use idevice::{mobile_image_mounter::ImageMounter, RsdService};
use sha2::{Digest, Sha256};
use std::path::Path;

/// The image ddi.py downloads, as Pallas's Mac installer pins it.
const FILES: [(&str, &str); 3] = [
    ("Image.dmg", "05fd807da5e19f030fa4941f24800c965c6c77982ab572dd5d1ef778fb69f9ca"),
    ("Image.dmg.trustcache", "36af60889ff5a737874a26daeb8e1a0139ebfebec6ec2e4d8f6a3c1bf1dce35c"),
    ("BuildManifest.plist", "8edd4a2f4f4ef1fbd7bfe49785d8badc673d1395d1d94d85b132ca8ab5ecaf54"),
];

fn developer(devices: &[plist::Value]) -> bool {
    devices.iter().any(|v| {
        v.as_dictionary().is_some_and(|d| {
            d.get("MountPath").and_then(plist::Value::as_string).is_some_and(|s| s.contains("Developer"))
                || d.get("PersonalizedImageType").and_then(plist::Value::as_string) == Some("DeveloperDiskImage")
        })
    })
}

async fn mounted(conn: &mut Connection) -> Result<bool> {
    let mut mounter = ImageMounter::connect_rsd(&mut conn.adapter, &mut conn.handshake)
        .await
        .map_err(|e| Fail::new("Cannot reach the developer image service", e.to_string()))?;
    let devices = mounter
        .copy_devices()
        .await
        .map_err(|e| Fail::new("Cannot read the mounted developer images", e.to_string()))?;
    Ok(developer(&devices))
}

/// Mounts the image unless it is already mounted.
pub async fn ensure(conn: &mut Connection, home: &Path) -> Result<()> {
    if mounted(conn).await? {
        ui::ok("Developer image already mounted");
        return Ok(());
    }
    ui::activity("mounting the developer image the runner needs");
    let dir = home.join("ddi");
    let mut payloads = Vec::new();
    for (name, hash) in FILES {
        let bytes = std::fs::read(dir.join(name))
            .map_err(|e| Fail::new("开发者运行环境还没下载，请重试。", format!("{name}: {e}")))?;
        if hex::encode(Sha256::digest(&bytes)) != hash {
            return Err(Fail::new("开发者运行环境校验失败，请重试。", name.to_string()));
        }
        payloads.push(bytes);
    }
    let chip = conn
        .handshake
        .properties
        .get("UniqueChipID")
        .and_then(|v| v.as_unsigned_integer().or_else(|| v.as_signed_integer().map(|i| i as u64)))
        .ok_or_else(|| Fail::new("This device did not report its chip ID", ""))?;
    let manifest = payloads.pop().unwrap();
    let trust_cache = payloads.pop().unwrap();
    let image = payloads.pop().unwrap();
    let mut mounter = ImageMounter::connect_rsd(&mut conn.adapter, &mut conn.handshake)
        .await
        .map_err(|e| Fail::new("Cannot reach the developer image service", e.to_string()))?;
    mounter
        .mount_personalized_rsd(&mut conn.adapter, &mut conn.handshake, image, trust_cache, &manifest, None, chip)
        .await
        .map_err(|e| Fail::new("设备没能挂载开发者运行环境：请保持解锁和联网后重试。", e.to_string()))?;
    if !mounted(conn).await? {
        return Err(Fail::new("开发者运行环境挂载后没有出现。", ""));
    }
    ui::ok("Developer image mounted");
    Ok(())
}
