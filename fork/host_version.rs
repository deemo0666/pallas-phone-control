// CFBundleShortVersionString has up to three numeric components.
pub(super) fn supported(version: &str) -> bool {
    let mut parts = [0u32; 3];
    for (index, value) in version.split('.').enumerate() {
        if index >= parts.len() || !value.bytes().all(|byte| byte.is_ascii_digit()) {
            return false;
        }
        let Ok(number) = value.parse() else { return false };
        parts[index] = number;
    }
    parts == [0, 3, 1] || parts >= [0, 3, 4]
}

#[cfg(test)]
mod tests {
    use super::supported;

    #[test]
    fn supports_legacy_exception_and_minimum_or_later() {
        for version in ["0.3.1", "0.3.4", "0.3.10", "0.4.0", "0.10", "1"] {
            assert!(supported(version), "{version}");
        }
        for version in ["", "0.3", "0.3.2", "0.3.3", "0.4.", "1.0.0.0", "v1", "1.0-beta"] {
            assert!(!supported(version), "{version}");
        }
    }
}
