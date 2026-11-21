use crate::{
    account,
    fail::{Fail, Result},
    install, seed,
    tunnel::{self, Connection, DeviceInfo},
    ui, Args,
};
use apple_codesign_quick::{
    sign_bundle, BundleSigningSettings, ProvisioningProfile, RustCryptoCmsSigner,
};
use idevice::{
    house_arrest::HouseArrestClient, installation_proxy::InstallationProxyClient, RsdService,
};
use isideload::{
    dev::developer_session::{AppIdsApi, DevicesApi},
    sideload::{
        application::Application, builder::MaxCertsBehavior, cert_identity::CertificateIdentity,
    },
    util::fs_storage::FsStorage,
};
use plist::{Dictionary, Value};
use sha2::{Digest, Sha256};
use std::{
    path::Path,
    time::{Duration, SystemTime},
};
use x509_cert::der::Encode;

/// The released Pallas, used when the plugin does not say which app it runs in.
const DEFAULT_HOST: &str = "io.github.maao514.harborchat";
const KEYFILE: &str = "/Documents/.screen-runner-key";

/// The Pallas the plugin runs in: the user app whose data container is PALLAS_HOST_CONTAINER
/// (…/Containers/Data/Application/<UUID>). Pairing goes to the app that ran setup, whatever
/// its bundle ID, signer or version; an app that can run this plugin has what the runner needs.
async fn host_app(conn: &mut Connection) -> Result<String> {
    let Some(container) = std::env::var("PALLAS_HOST_CONTAINER").ok().filter(|s| !s.is_empty()) else {
        app(conn, DEFAULT_HOST).await?;
        return Ok(DEFAULT_HOST.into());
    };
    let uuid = container.trim_end_matches('/').rsplit('/').next().unwrap_or("").to_ascii_uppercase();
    if uuid.len() != 36 {
        return Err(Fail::new("Invalid Pallas container", container));
    }
    let mut proxy = InstallationProxyClient::connect_rsd(&mut conn.adapter, &mut conn.handshake)
        .await
        .at("Installation service unavailable")?;
    let apps = proxy.get_apps(Some("User"), None).await.at("App lookup failed")?;
    let mut found = apps.into_iter().filter(|(_, info)| {
        info.as_dictionary()
            .and_then(|d| d.get("Container"))
            .and_then(Value::as_string)
            .is_some_and(|path| path.trim_end_matches('/').to_ascii_uppercase().ends_with(&uuid))
    });
    match (found.next(), found.next()) {
        (Some((id, _)), None) => Ok(id),
        (None, _) => Err(Fail::new("This Pallas was not found among installed apps", uuid)),
        _ => Err(Fail::new("More than one app has this Pallas container", uuid)),
    }
}

pub fn renewing() -> bool {
    std::env::var_os("PALLAS_RENEWAL").is_some()
}

#[derive(serde::Deserialize, serde::Serialize)]
struct Receipt {
    udid: String,
    bundle: String,
    link_hash: String,
    cert_hash: String,
    expires: u64,
    /// The Pallas whose plugin made this install; absent in receipts from before it could vary.
    #[serde(default)]
    host: Option<String>,
    /// Every Pallas the runner serves, with a hash of the key each holds.
    #[serde(default)]
    links: std::collections::BTreeMap<String, String>,
}

/// The pairing key in a Pallas's Documents, or None when it has none (or the app is gone).
async fn read_key(conn: &mut Connection, host: &str) -> Result<Option<String>> {
    use idevice::afc::{errors::AfcError, opcode::AfcFopenMode};
    let mut docs = match HouseArrestClient::connect_rsd(&mut conn.adapter, &mut conn.handshake)
        .await
        .at("Host container unavailable")?
        .vend_documents(host)
        .await
    {
        Ok(docs) => docs,
        Err(e) => return Err(Fail::new("Cannot open Pallas Documents", format!("{host}: {e}"))),
    };
    match docs.get_file_info(KEYFILE).await {
        Ok(_) => {
            let data = docs.open(KEYFILE, AfcFopenMode::RdOnly).await.at("Cannot read existing link")?
                .read_entire().await.at("Cannot read existing link")?;
            let key = String::from_utf8(data).at("Invalid existing link")?;
            if key.len() != 64 || !key.bytes().all(|c| c.is_ascii_hexdigit()) {
                return Err(Fail::new("Invalid existing link", host.to_string()));
            }
            Ok(Some(key))
        }
        Err(idevice::IdeviceError::Afc(AfcError::ObjectNotFound)) => Ok(None),
        Err(e) => Err(Fail::new("Cannot inspect existing host link", e.to_string())),
    }
}

fn hash(key: &str) -> String {
    hex::encode(Sha256::digest(key.as_bytes()))
}

trait Stage<T> {
    fn at(self, name: &'static str) -> Result<T>;
}
impl<T, E: std::fmt::Display> Stage<T> for std::result::Result<T, E> {
    fn at(self, name: &'static str) -> Result<T> {
        self.map_err(|e| Fail::new(name, e.to_string()))
    }
}

async fn app(conn: &mut Connection, id: &str) -> Result<Dictionary> {
    let mut proxy = InstallationProxyClient::connect_rsd(&mut conn.adapter, &mut conn.handshake)
        .await
        .at("Installation service unavailable")?;
    let mut found = proxy
        .get_apps(Some("User"), Some(vec![id.into()]))
        .await
        .at("App lookup failed")?;
    found
        .remove(id)
        .and_then(Value::into_dictionary)
        .ok_or_else(|| Fail::new("Expected app missing", id))
}

fn select_certificate(certs: &Vec<isideload::dev::certificates::DevelopmentCertificate>) -> Option<Vec<String>> {
    // This callback runs only after Apple's certificate-limit response.
    ui::warn("Apple 开发证书名额已满（Apple 7460）");
    if crate::web::page().is_none() { return None; }
    let active = std::env::var("PALLAS_ACTIVE_CERT_SHA256").ok();
    let eligible: Vec<_> = certs.iter().filter(|cert| {
        cert.serial_number.is_some() && cert.cert_content.as_ref().is_some_and(|der| {
            Some(hex::encode(Sha256::digest(der.as_ref()))) != active
        })
    }).collect();
    let mut choices = vec!["保留现有证书，结束本次安装".to_owned()];
    for cert in &eligible {
        choices.push(format!("{} · {}", cert.machine_name.as_deref().unwrap_or("开发证书"),
            cert.serial_number.as_deref().unwrap()));
    }
    let index = ui::choose("保留证书，或选择一张要撤销的开发证书", &choices)?.checked_sub(1)?;
    let cert = eligible.get(index)?;
    if !ui::confirm(&format!("确认撤销 {}？所有设备上用这张证书签名的 App 都可能需要重新签装。此操作不可撤销。", choices[index+1]), false) {
        return None;
    }
    Some(vec![cert.serial_number.clone()?])
}

fn select_prompt(
    certs: Vec<isideload::dev::certificates::DevelopmentCertificate>,
) -> std::pin::Pin<Box<dyn std::future::Future<Output = std::result::Result<Option<Vec<String>>, rootcause::Report>> + Send>> {
    Box::pin(async move { Ok(tokio::task::block_in_place(|| select_certificate(&certs))) })
}

/// Whether Apple still lists a development certificate for the signing key
/// stored for `email`. Renewal must not make a new one.
async fn existing_certificate(
    storage: &Path,
    email: &str,
    dev: &mut isideload::dev::developer_session::DeveloperSession,
    team: &isideload::dev::teams::DeveloperTeam,
) -> Result<bool> {
    use isideload::dev::certificates::CertificatesApi;
    use rsa::pkcs8::{DecodePrivateKey, EncodePublicKey};
    use x509_cert::der::Decode;
    let key = std::fs::read(storage.join(hex::encode(Sha256::digest(email.as_bytes()))).join("key"))
        .map_err(|e| Fail::new("Signing key is missing. Run a manual install.", e.to_string()))?;
    let key = rsa::RsaPrivateKey::from_pkcs8_der(&key)
        .map_err(|e| Fail::new("Signing key is unreadable. Run a manual install.", e.to_string()))?;
    let public = key.to_public_key().to_public_key_der()
        .map_err(|e| Fail::new("Signing key is unreadable. Run a manual install.", e.to_string()))?;
    let certs = dev.list_ios_certs(team).await.at("Certificate check failed")?;
    Ok(certs.iter().filter_map(|c| c.cert_content.as_ref()).any(|der| {
        x509_cert::Certificate::from_der(der.as_ref()).ok()
            .and_then(|cert| cert.tbs_certificate.subject_public_key_info.to_der().ok())
            .is_some_and(|spki| spki == public.as_bytes())
    }))
}

/// The signing identity for a manual install or a reveal: the stored one, or a new certificate
/// after the person chooses which old one to revoke when the team has no room.
async fn new_identity(
    email: &str,
    dev: &mut isideload::dev::developer_session::DeveloperSession,
    team: &isideload::dev::teams::DeveloperTeam,
    storage: &FsStorage,
) -> Result<CertificateIdentity> {
    CertificateIdentity::retrieve(
        "Pallas siboot",
        email,
        dev,
        team,
        storage,
        &MaxCertsBehavior::Prompt(select_prompt as account::CertPrompt),
    )
    .await
    .map_err(|e| {
        let raw = crate::error_text::report_text(&e);
        for node in e.iter_reports() {
            if let Some(isideload::SideloadError::DeveloperError(code, _)) = node.downcast_current_context::<isideload::SideloadError>() {
                let advice = match *code {
                    7460 => "Apple 开发证书名额已满".to_owned(),
                    _ => "Apple 拒绝了开发证书请求".to_owned(),
                };
                return Fail::new(format!("{advice}（Apple {code}）"), raw);
            }
        }
        let kind = if raw.contains("max attempts") { "CSR 重试耗尽" }
            else if raw.contains("Failed to generate CSR") { "无法创建 CSR" }
            else if raw.contains("after submitting CSR") { "Apple 尚未列出新证书" }
            else if raw.contains("storage") || raw.contains("DER") { "本机签名密钥读写失败" }
            else { "无法取得签名身份" };
        Fail::new(format!("开发证书：{kind}"), raw)
    })
}

/// A free team's profile for this certificate, App ID and device that ends within eight days.
/// Returns its expiry in Unix seconds.
fn check_profile(parsed: &ProvisioningProfile, udid: &str, cert_der: &[u8], team_id: &str, id: &str) -> Result<u64> {
    let p = parsed.plist();
    let expiry: SystemTime = p
        .get("ExpirationDate")
        .and_then(Value::as_date)
        .ok_or_else(|| Fail::new("Missing expiry", ""))?
        .into();
    // A paid team's profile lasts a year and has no LocalProvision: the runner and its renewal are
    // built around a free Personal Team, so say plainly which account to use instead.
    if p.get("LocalProvision").and_then(Value::as_boolean) != Some(true) {
        return Err(Fail::new(
            "这个 Apple 账号是付费开发者账号。手机操控要用免费 Apple 账号（个人团队），请换免费账号重新登录。",
            "profile has no LocalProvision",
        ));
    }
    if !p
            .get("ProvisionedDevices")
            .and_then(Value::as_array)
            .is_some_and(|a| a.iter().any(|v| v.as_string() == Some(udid)))
        || !p
            .get("DeveloperCertificates")
            .and_then(Value::as_array)
            .is_some_and(|a| a.iter().any(|v| v.as_data() == Some(cert_der)))
        || parsed
            .entitlements()
            .get("application-identifier")
            .and_then(Value::as_string)
            != Some(&format!("{team_id}.{id}"))
        || expiry
            .duration_since(SystemTime::now())
            .at("Expired profile")?
            > Duration::from_secs(8 * 86400)
    {
        return Err(Fail::new(
            "Profile does not match a free team, certificate and target device",
            "",
        ));
    }
    Ok(expiry.duration_since(SystemTime::UNIX_EPOCH).at("Invalid expiration")?.as_secs())
}

fn runner_id(team_id: &str) -> String {
    format!("io.dshlocal.sideload.t{}.screen.xctrunner", team_id.to_lowercase())
}

fn check_runner_ipa(archive: &str) -> Result<()> {
    let bytes = std::fs::read(archive).at("Runner IPA missing")?;
    // black_box keeps the expected hash as one string in the binary, where the package checks find it.
    if hex::encode(Sha256::digest(&bytes)) != std::hint::black_box(env!("PALLAS_RUNNER_SHA256")) {
        return Err(Fail::new("Runner IPA checksum mismatch", ""));
    }
    Ok(())
}

/// Signs the runner for a device known only by its UDID, from the profile it installed, and puts
/// the app in OUT/Payload. Nothing is installed: the plugin offers the app from a Safari page, and
/// iOS shows the hidden Developer Mode switch once an app with a profile naming this device is
/// offered, whether or not the install goes through. The App ID, certificate and Apple session are
/// the ones the later install uses, so that install asks for nothing new.
pub async fn reveal(args: &Args) -> Result<()> {
    let archive = args.ipa.as_deref().ok_or_else(|| Fail::new("Runner IPA required", ""))?;
    let udid = args.udid.as_deref().ok_or_else(|| Fail::new("UDID required", ""))?;
    let out = args.out.as_deref().ok_or_else(|| Fail::new("Output folder required", ""))?;
    check_runner_ipa(archive)?;
    ui::step(4, "Sign in with your free Apple Account");
    let mut session = account::sign_in(args).await?;
    let team = &session.selected;
    let dev = &mut session.developer;
    let id = runner_id(&team.team_id);
    dev.ensure_device_registered(team, "Pallas", udid, None)
        .await
        .at("Device registration failed")?;
    let ids = dev.list_app_ids(team, None).await.at("Cannot look up App IDs")?;
    let app_id = match ids.app_ids.into_iter().find(|a| a.identifier == id) {
        Some(a) => a,
        None => dev
            .add_app_id(team, "Pallas Phone Control", &id, None)
            .await
            .at("Cannot register runner ID")?,
    };
    ui::step(5, "Sign the Pallas runner");
    let storage = FsStorage::new(args.home.join("isideload"));
    let cert = new_identity(&session.email, dev, team, &storage).await?;
    let profile = dev
        .download_team_provisioning_profile(team, &app_id, None)
        .await
        .at("Cannot obtain profile")?;
    let bytes = profile.encoded_profile.as_ref();
    let parsed = ProvisioningProfile::parse(bytes).at("Invalid profile")?;
    let cert_der = cert.certificate.to_der().at("Invalid certificate")?;
    check_profile(&parsed, udid, &cert_der, &team.team_id, &id)?;
    let unpack = Application::new(Path::new(archive).into()).at("Cannot unpack runner")?;
    let bundle = &unpack.bundle.bundle_dir;
    for dir in [bundle.clone(), bundle.join("PlugIns/DSHScreen.xctest")] {
        let path = dir.join("Info.plist");
        let mut info: Dictionary = plist::from_file(&path).at("Invalid runner metadata")?;
        info.insert("CFBundleIdentifier".into(), id.clone().into());
        plist::to_file_xml(path, &info).at("Cannot prepare runner metadata")?;
    }
    let chain = cert.profile_to_certificate_chain(&parsed).at("Invalid signing chain")?;
    let signer = RustCryptoCmsSigner::new(cert.private_key, cert.certificate, chain);
    let mut settings = BundleSigningSettings::new(&team.team_id, parsed.entitlements().clone(), Some(&signer));
    settings.embedded_mobileprovision = Some(bytes);
    sign_bundle(bundle, &settings).at("Runner signing failed")?;
    let payload = out.join("Payload");
    std::fs::create_dir_all(&payload).at("Cannot stage signed runner")?;
    let name = bundle.file_name().ok_or_else(|| Fail::new("Cannot stage signed runner", ""))?;
    std::fs::rename(bundle, payload.join(name)).at("Cannot stage signed runner")?;
    ui::ok("Runner signed for this device");
    ui::finish(&format!("Signed {id} for {udid}"), &[]);
    Ok(())
}

pub async fn install(args: &Args, mut conn: Connection, device: &DeviceInfo) -> Result<()> {
    let archive = args
        .ipa
        .as_ref()
        .ok_or_else(|| Fail::new("Runner IPA required", ""))?;
    check_runner_ipa(archive)?;
    let receipt_path = args.home.join("runner-receipt.json");
    let previous: Option<Receipt> = if renewing() {
        let data = std::fs::read(&receipt_path).at("Complete a manual install before renewing")?;
        Some(serde_json::from_slice(&data).at("Invalid renewal receipt")?)
    } else { None };
    // The last install's receipt names the hosts the installed runner serves; keep them.
    let stored: Option<Receipt> = match &previous {
        Some(_) => None,
        None => std::fs::read(&receipt_path).ok().and_then(|d| serde_json::from_slice(&d).ok()),
    };
    let earlier = previous.as_ref().or(stored.as_ref());
    let host = host_app(&mut conn).await?;
    ui::detail(&format!("linking the runner to {host}"));
    // Reuse the host's current link when upgrading: an interrupted installation
    // then leaves the previous runner and host able to authenticate.
    let key = match read_key(&mut conn, &host).await? {
        Some(key) => key,
        None => format!("{}{}", uuid::Uuid::new_v4().simple(), uuid::Uuid::new_v4().simple()),
    };
    let link_hash = hash(&key);
    if let Some(old) = &previous {
        let known = old.links.get(&host).cloned()
            .or_else(|| (old.host.as_deref().unwrap_or(DEFAULT_HOST) == host).then(|| old.link_hash.clone()));
        if old.udid != device.udid || known.as_deref() != Some(link_hash.as_str()) {
            return Err(Fail::new("Device or Pallas link changed. Run a manual install.", ""));
        }
        app(&mut conn, &old.bundle).await?;
    }
    // Every other Pallas the runner already serves, or that holds a key from an earlier install
    // (the released one paired by an installer before 0.5.4), stays linked with the key it has.
    let mut others: Vec<String> = earlier.map(|r| {
        let mut ids: Vec<String> = r.links.keys().cloned().collect();
        ids.push(r.host.clone().unwrap_or_else(|| DEFAULT_HOST.into()));
        ids
    }).unwrap_or_default();
    others.push(DEFAULT_HOST.into());
    let mut links: Vec<(String, String)> = vec![(host.clone(), key.clone())];
    for other in others {
        if links.iter().any(|(h, _)| *h == other) || app(&mut conn, &other).await.is_err() {
            continue;
        }
        match read_key(&mut conn, &other).await {
            Ok(Some(k)) => links.push((other, k)),
            Ok(None) => {}
            Err(e) => ui::detail(&format!("{} keeps no link: {}", other, e.advice)),
        }
    }
    ui::detail(&format!("runner serves {}", links.iter().map(|(h, _)| h.as_str()).collect::<Vec<_>>().join(", ")));
    drop(conn);
    ui::step(4, "Sign in with your free Apple Account");
    let mut session = account::sign_in(args).await?;
    let team = &session.selected;
    let dev = &mut session.developer;
    let id = runner_id(&team.team_id);
    if let Some(old) = &previous {
        if old.bundle != id { return Err(Fail::new("Apple team changed. Run a manual install.", "")); }
    } else {
        dev.ensure_device_registered(team, &device.name, &device.udid, None)
        .await
        .at("Device registration failed")?;
    }
    let ids = dev
        .list_app_ids(team, None)
        .await
        .at("Cannot look up App IDs")?;
    let app_id = match ids.app_ids.into_iter().find(|a| a.identifier == id) {
        Some(a) => a,
        None if renewing() => return Err(Fail::new("Runner App ID is missing", "")),
        None => dev
            .add_app_id(team, "Pallas Phone Control", &id, None)
            .await
            .at("Cannot register runner ID")?,
    };
    ui::step(5, "Sign the Pallas runner");
    let storage = FsStorage::new(args.home.join("isideload"));
    let cert = if renewing() {
        let email_hash = hex::encode(Sha256::digest(session.email.as_bytes()));
        if !args.home.join("isideload").join(email_hash).join("key").is_file() {
            return Err(Fail::new("Signing key is missing. Run a manual install.", ""));
        }
        if !existing_certificate(&args.home.join("isideload"), &session.email, dev, team).await? {
            return Err(Fail::new("Signing certificate is unavailable. Run a manual install.", ""));
        }
        // A match exists, so this finds it and asks Apple for nothing new.
        CertificateIdentity::retrieve("Pallas siboot", &session.email, dev, team, &storage,
            &MaxCertsBehavior::<account::CertPrompt>::Error)
            .await.at("Certificate check failed")?
    } else { new_identity(&session.email, dev, team, &storage).await? };
    let profile = dev
        .download_team_provisioning_profile(team, &app_id, None)
        .await
        .at("Cannot obtain profile")?;
    let bytes = profile.encoded_profile.as_ref();
    let parsed = ProvisioningProfile::parse(bytes).at("Invalid profile")?;
    let cert_der = cert.certificate.to_der().at("Invalid certificate")?;
    let expires = check_profile(&parsed, &device.udid, &cert_der, &team.team_id, &id)?;
    let cert_hash = hex::encode(Sha256::digest(&cert_der));
    if let Some(old) = &previous {
        if old.cert_hash != cert_hash {
            return Err(Fail::new("Signing certificate changed. Run a manual install.", ""));
        }
        if expires <= old.expires {
            return Err(Fail::new("Apple has not extended the profile yet. Try again later.", ""));
        }
    }
    let unpack = Application::new(Path::new(archive).into()).at("Cannot unpack runner")?;
    let bundle = &unpack.bundle.bundle_dir;
    for dir in [bundle.clone(), bundle.join("PlugIns/DSHScreen.xctest")] {
        let path = dir.join("Info.plist");
        let mut info: Dictionary = plist::from_file(&path).at("Invalid runner metadata")?;
        info.insert("CFBundleIdentifier".into(), id.clone().into());
        if dir == *bundle {
            info.insert("DSHScreenKey".into(), key.clone().into());
            info.insert("DSHScreenHost".into(), host.clone().into());
            // Runners from 0.5.4 serve every host listed here, each on its own key.
            info.insert("DSHScreenHosts".into(), Value::Array(links.iter().map(|(h, k)| {
                let mut entry = Dictionary::new();
                entry.insert("host".into(), h.clone().into());
                entry.insert("key".into(), k.clone().into());
                Value::Dictionary(entry)
            }).collect()));
            let mut url = Dictionary::new();
            url.insert(
                "CFBundleURLSchemes".into(),
                // Pallas before 0.5.5 opens only the old scheme.
                Value::Array(vec!["pallas-screen-runner".into(), "dsh-screen-runner".into()]),
            );
            info.insert("CFBundleURLTypes".into(), Value::Array(vec![url.into()]));
        }
        plist::to_file_xml(path, &info).at("Cannot prepare runner metadata")?;
    }
    let chain = cert
        .profile_to_certificate_chain(&parsed)
        .at("Invalid signing chain")?;
    let signer = RustCryptoCmsSigner::new(cert.private_key, cert.certificate, chain);
    let mut settings =
        BundleSigningSettings::new(&team.team_id, parsed.entitlements().clone(), Some(&signer));
    settings.embedded_mobileprovision = Some(bytes);
    sign_bundle(bundle, &settings).at("Runner signing failed")?;
    ui::ok("Personal Team profile verified and runner signed");
    ui::step(6, "Install the runner on this device");
    let mut conn = tunnel::open(args.device, &args.pairing_path()).await?;
    let stage = tempfile::tempdir().at("Cannot stage signed runner")?;
    let dest = stage
        .path()
        .join(format!("Pallas-{}.app", uuid::Uuid::new_v4()));
    std::fs::rename(bundle, &dest).at("Cannot stage signed runner")?;
    install::install(&mut conn, &dest).await?;
    app(&mut conn, &id).await?;
    ui::ok("Runner installation confirmed");
    // An XCTest runner starts only with the developer image mounted (none on a device that never met Xcode).
    crate::ddi::ensure(&mut conn, &args.home).await?;
    ui::step(7, "Connect Pallas to the runner");
    let mut docs = HouseArrestClient::connect_rsd(&mut conn.adapter, &mut conn.handshake)
        .await
        .at("Host container unavailable")?
        .vend_documents(&host)
        .await
        .at("Cannot open Pallas Documents")?;
    let tmp = format!("{}.{}", KEYFILE, uuid::Uuid::new_v4());
    seed::write_verified(&mut docs, &tmp, key.as_bytes()).await?;
    docs.rename(&tmp, KEYFILE)
        .await
        .at("Cannot activate host link")?;
    use idevice::afc::opcode::AfcFopenMode;
    let actual = docs
        .open(KEYFILE, AfcFopenMode::RdOnly)
        .await
        .at("Cannot verify host link")?
        .read_entire()
        .await
        .at("Cannot verify host link")?;
    if actual != key.as_bytes() {
        return Err(Fail::new("Host link mismatch", ""));
    }
    let links = links.iter().map(|(h, k)| (h.clone(), hash(k))).collect();
    let receipt = Receipt { udid: device.udid.clone(), bundle: id, link_hash, cert_hash, expires, host: Some(host), links };
    let mut tmp = tempfile::NamedTempFile::new_in(&args.home).at("Cannot record install")?;
    serde_json::to_writer(&mut tmp, &receipt).at("Cannot record install")?;
    tmp.as_file().sync_all().at("Cannot save install receipt")?;
    tmp.persist(receipt_path).at("Cannot activate install receipt")?;
    ui::finish("Pallas runner installed and linked", &[]);
    Ok(())
}
