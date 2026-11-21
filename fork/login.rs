//! Apple Account sign-in for the Pallas signer, on upstream isideload.
//!
//! Written for Pallas (MIT). One folder per account under the storage
//! directory, named as isideload names it (`sha256(email)`), so the signing key
//! isideload keeps there stays with the account. Next to it we keep the
//! anisette identity and the Xcode token, so a later run (a scheduled renewal
//! above all) can open the developer session again without the password.

use std::future::Future;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use isideload::anisette::remote_v3::RemoteV3AnisetteProvider;
use isideload::anisette::AnisetteDataGenerator;
use isideload::auth::apple_account::{
    AppToken, AppleAccount, TwoFactorCallbackParams, TwoFactorCallbackResponse,
};
use isideload::auth::grandslam::GrandSlam;
use isideload::dev::developer_session::DeveloperSession;
use isideload::dev::device_type::{dev_url, DeveloperDeviceType};
use isideload::dev::teams::{DeveloperTeam, TeamsApi};
use isideload::util::fs_storage::FsStorage;
use rootcause::Report;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tokio::sync::RwLock;

const TOKEN_FILE: &str = "pallas_token.json";
/// A token this close to its end is not worth trying.
const MARGIN_SECS: u64 = 15 * 60;

/// Kept for callers that recognise this text; this module never returns it.
pub(crate) const ANDROID_ADI_SKIP: &str =
    "this anisette server uses Android ADI, which Apple refuses for developer sign-in";

#[derive(Serialize, Deserialize)]
struct SavedToken {
    apple_id: String,
    adsid: String,
    token: String,
    duration: u64,
    /// Unix seconds.
    expires: u64,
    anisette: String,
}

pub(crate) fn account_dir(storage: &Path, apple_id: &str) -> PathBuf {
    storage.join(hex::encode(Sha256::digest(apple_id.as_bytes())))
}

fn now() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

/// Apple states token expiry in milliseconds; accept seconds as well.
fn seconds(expiry: u64) -> u64 {
    if expiry > 100_000_000_000 { expiry / 1000 } else { expiry }
}

fn generator(dir: &Path, anisette: &str) -> Result<AnisetteDataGenerator, String> {
    let provider = RemoteV3AnisetteProvider::new(
        anisette,
        Box::new(FsStorage::new(dir.to_owned())),
        "0".to_string(),
    )
    .map_err(|e| crate::error_text::report_text(&e))?;
    Ok(AnisetteDataGenerator::new(Arc::new(RwLock::new(provider))))
}

fn read_saved(dir: &Path) -> Option<SavedToken> {
    serde_json::from_slice(&std::fs::read(dir.join(TOKEN_FILE)).ok()?).ok()
}

fn write_saved(dir: &Path, saved: &SavedToken) {
    let Ok(json) = serde_json::to_vec(saved) else { return };
    let tmp = dir.join(format!("{TOKEN_FILE}.tmp"));
    if std::fs::write(&tmp, json).is_ok() {
        let _ = std::fs::rename(tmp, dir.join(TOKEN_FILE));
    }
}

/// Codes the signer stops with when the account is not a free Personal Team. setup.py turns
/// them into `next: paid_account` and the agent explains in the person's language.
pub(crate) const PAID_TEAM: &str = "paid_team";
pub(crate) const MULTIPLE_TEAMS: &str = "multiple_teams";
/// Caught only by the profile, after the device, App ID and certificate were set up.
pub(crate) const PAID_TEAM_PROFILE: &str = "paid_team_profile";

/// A team as Apple's team list describes it, with the programs it belongs to.
#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct TeamMembership {
    team_id: String,
    r#type: Option<String>,
    #[serde(default)]
    memberships: Vec<Membership>,
}

#[derive(Deserialize)]
struct Membership {
    name: Option<String>,
}

/// An organisation, or an individual whose programs name no free one ("Xcode Free Provisioning
/// Program"); AltSign reads the team list the same way. Anything else counts as free, so a
/// change on Apple's side cannot lock free accounts out: the profile check still stops a paid one.
fn paid(team: &TeamMembership) -> bool {
    match team.r#type.as_deref() {
        Some("Company/Organization") | Some("In-House") => true,
        Some("Individual") => {
            !team.memberships.is_empty()
                && !team.memberships.iter().any(|m| {
                    m.name.as_deref().is_some_and(|n| n.to_ascii_lowercase().contains("free"))
                })
        }
        _ => false,
    }
}

/// Whether `team_id` is a paid team, read before the signer registers the device, adds an App ID
/// or asks for a certificate. False when Apple's answer cannot be read.
pub(crate) async fn is_paid_team(developer: &mut DeveloperSession, team_id: &str) -> bool {
    match developer
        .send_dev_request::<Vec<TeamMembership>>(&dev_url("listTeams", DeveloperDeviceType::Any), None, "teams")
        .await
    {
        Ok(list) => list.iter().find(|t| t.team_id == team_id).is_some_and(paid),
        Err(_) => false,
    }
}

async fn teams(mut developer: DeveloperSession) -> Result<(DeveloperSession, Vec<DeveloperTeam>), String> {
    let list = developer
        .list_teams()
        .await
        .map_err(|e| crate::error_text::report_text(&e))?;
    Ok((developer, list))
}

/// A developer session from a saved token, checked by listing its teams.
async fn reopen(dir: &Path, saved: &SavedToken) -> Result<(DeveloperSession, Vec<DeveloperTeam>), String> {
    let generator = generator(dir, &saved.anisette)?;
    let info = generator
        .get_client_info()
        .await
        .map_err(|e| crate::error_text::report_text(&e))?;
    let client = GrandSlam::new(info, false, None)
        .await
        .map_err(|e| crate::error_text::report_text(&e))?;
    let token = AppToken { token: saved.token.clone(), duration: saved.duration, expiry: saved.expires * 1000 };
    teams(DeveloperSession::new(token, saved.adsid.clone(), Arc::new(client), generator)).await
}

fn usable(saved: &SavedToken, apple_id: &str) -> bool {
    saved.apple_id == apple_id && saved.expires > now() + MARGIN_SECS
}

/// Signs `apple_id` in through `anisette` and lists its teams. A saved token for
/// the account is tried first; after a full sign-in the new token is saved.
pub(crate) async fn open<C, Fut>(
    apple_id: &str,
    password: &str,
    anisette: &str,
    storage: &Path,
    two_factor: C,
) -> Result<(DeveloperSession, Vec<DeveloperTeam>), String>
where
    C: Fn(TwoFactorCallbackParams) -> Fut + Send + Sync,
    Fut: Future<Output = Result<TwoFactorCallbackResponse, Report>> + Send,
{
    let dir = account_dir(storage, apple_id);
    std::fs::create_dir_all(&dir).map_err(|e| format!("{}: {e}", dir.display()))?;
    if let Some(saved) = read_saved(&dir).filter(|s| usable(s, apple_id) && s.anisette == anisette) {
        if let Ok(opened) = reopen(&dir, &saved).await {
            return Ok(opened);
        }
    }

    let mut account = AppleAccount::new(apple_id, generator(&dir, anisette)?, false, None, Some(3))
        .await
        .map_err(|e| crate::error_text::report_text(&e))?;
    account
        .login(password, two_factor)
        .await
        .map_err(|e| crate::error_text::report_text(&e))?;
    let adsid = account
        .spd
        .as_ref()
        .and_then(|spd| spd.get("adsid"))
        .and_then(|v| v.as_string())
        .map(str::to_string)
        .ok_or("Apple's sign-in reply had no account identifier")?;
    let developer = DeveloperSession::from_account(&mut account)
        .await
        .map_err(|e| crate::error_text::report_text(&e))?;
    let (developer, list) = teams(developer).await?;
    if let Some(token) = developer_token(&mut account).await {
        write_saved(&dir, &SavedToken {
            apple_id: apple_id.to_string(),
            adsid,
            token: token.token,
            duration: token.duration,
            expires: seconds(token.expiry),
            anisette: anisette.to_string(),
        });
    }
    Ok((developer, list))
}

/// The Xcode token again, to save: DeveloperSession keeps its copy private.
async fn developer_token(account: &mut AppleAccount) -> Option<AppToken> {
    account.get_app_token("xcode.auth").await.ok()
}

/// Opens the one account this installation saved a usable token for. `None`
/// when there is none, or more than one, or the token no longer works.
pub(crate) async fn resume_single(
    storage: &Path,
    anisette: &str,
) -> Result<Option<(String, DeveloperSession, Vec<DeveloperTeam>)>, String> {
    let Ok(entries) = std::fs::read_dir(storage) else { return Ok(None) };
    let mut found = entries.flatten().filter_map(|entry| {
        let saved = read_saved(&entry.path())?;
        (entry.path() == account_dir(storage, &saved.apple_id) && usable(&saved, &saved.apple_id))
            .then_some((entry.path(), saved))
    });
    let Some((dir, mut saved)) = found.next() else { return Ok(None) };
    if found.next().is_some() {
        return Ok(None);
    }
    // The anisette identity belongs to the server that made it.
    if saved.anisette != anisette {
        saved.anisette = anisette.to_string();
    }
    match reopen(&dir, &saved).await {
        Ok((developer, list)) => Ok(Some((saved.apple_id, developer, list))),
        Err(e) if transient(&e) => Err(e),
        Err(_) => Ok(None),
    }
}

/// Network trouble, worth reporting rather than asking for the password again.
fn transient(error: &str) -> bool {
    let e = error.to_ascii_lowercase();
    ["timed out", "connection", "dns", "network", "error sending request"].iter().any(|k| e.contains(k))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn team(kind: &str, programs: &[&str]) -> TeamMembership {
        TeamMembership {
            team_id: "T".into(),
            r#type: Some(kind.into()),
            memberships: programs.iter().map(|n| Membership { name: Some((*n).into()) }).collect(),
        }
    }

    #[test]
    fn paid_teams_from_the_team_list() {
        assert!(!paid(&team("Individual", &["Xcode Free Provisioning Program"])));
        assert!(paid(&team("Individual", &["Apple Developer Program"])));
        assert!(paid(&team("Company/Organization", &["Apple Developer Program"])));
        assert!(paid(&team("In-House", &[])));
        // No programs listed, or a type we do not know: free, the profile check is the backstop.
        assert!(!paid(&team("Individual", &[])));
        assert!(!paid(&team("Something new", &["Apple Developer Program"])));
        // Apple's plist shape, as the dev request reads it.
        let mut program = plist::Dictionary::new();
        program.insert("name".into(), "Xcode Free Provisioning Program".into());
        let mut entry = plist::Dictionary::new();
        entry.insert("teamId".into(), "ABC".into());
        entry.insert("type".into(), "Individual".into());
        entry.insert("memberships".into(), plist::Value::Array(vec![program.into()]));
        let parsed: Vec<TeamMembership> = plist::from_value(&plist::Value::Array(vec![entry.into()])).unwrap();
        assert_eq!(parsed[0].team_id, "ABC");
        assert!(!paid(&parsed[0]));
    }

    #[test]
    fn account_folder_is_the_email_hash() {
        let dir = account_dir(Path::new("/s"), "a@b.c");
        assert_eq!(dir, Path::new("/s").join(hex::encode(Sha256::digest(b"a@b.c"))));
    }

    #[test]
    fn expiry_in_ms_or_s() {
        assert_eq!(seconds(1_800_000_000_000), 1_800_000_000);
        assert_eq!(seconds(1_800_000_000), 1_800_000_000);
    }

    /// Network: provisions an anisette identity and opens GrandSlam, no account needed.
    /// `cargo test -- --ignored anisette_provisions`
    #[tokio::test(flavor = "multi_thread")]
    #[ignore]
    async fn anisette_provisions() {
        crate::install_crypto();
        for server in ["https://ani.iloader.app", "https://mac-ani.jkcoxson.com"] {
            let dir = std::env::temp_dir().join(format!("pallas-anisette-{}", std::process::id()));
            let _ = std::fs::remove_dir_all(&dir);
            std::fs::create_dir_all(&dir).unwrap();
            let mut generator = generator(&dir, server).unwrap();
            let info = generator.get_client_info().await.unwrap();
            let client = Arc::new(GrandSlam::new(info, false, None).await.unwrap());
            let data = generator.get_anisette_data(client).await;
            println!("{server}: {}", if data.is_ok() { "ok" } else { "failed" });
            data.unwrap();
            assert!(dir.join("anisette_state").exists() || std::fs::read_dir(&dir).unwrap().count() > 0);
        }
    }

    #[test]
    fn only_one_usable_account_resumes() {
        let storage = std::env::temp_dir().join(format!("pallas-login-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&storage);
        let save = |id: &str, expires: u64| {
            let dir = account_dir(&storage, id);
            std::fs::create_dir_all(&dir).unwrap();
            write_saved(&dir, &SavedToken { apple_id: id.into(), adsid: "x".into(), token: "t".into(),
                duration: 1, expires, anisette: "https://a".into() });
        };
        save("one@x.y", now() + 3600);
        save("old@x.y", now() + 60);
        let usable_count = std::fs::read_dir(&storage).unwrap().flatten()
            .filter_map(|e| read_saved(&e.path())).filter(|s| usable(s, &s.apple_id)).count();
        assert_eq!(usable_count, 1);
        let _ = std::fs::remove_dir_all(&storage);
    }
}
