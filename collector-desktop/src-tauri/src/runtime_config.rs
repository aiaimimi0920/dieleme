use std::io::Read;
use std::path::Path;

fn parse_api_base(raw: &[u8]) -> Option<String> {
    if raw.len() > 16_384 {
        return None;
    }
    let value: serde_json::Value = serde_json::from_slice(raw).ok()?;
    if value.get("version")?.as_u64()? != 1 {
        return None;
    }
    let api = value
        .get("environment")?
        .get("FAPAI_COLLECTOR_API_BASE")?
        .as_str()?;
    validate_api_base(api)
}

pub fn validate_api_base(api: &str) -> Option<String> {
    if api.len() > 8192 || api.chars().any(char::is_control) {
        return None;
    }
    let api = api.trim();
    let url = tauri::Url::parse(api).ok()?;
    if !matches!(url.scheme(), "http" | "https")
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
        || url.host_str().is_none()
        || !matches!(url.path(), "" | "/" | "/api" | "/api/")
    {
        return None;
    }
    Some(api.to_string())
}

pub fn api_base_for_script(script: &Path) -> Option<String> {
    let path = script.parent()?.parent()?.join("crow-desktop.runtime.json");
    let mut raw = Vec::new();
    std::fs::File::open(path)
        .ok()?
        .take(16_385)
        .read_to_end(&mut raw)
        .ok()?;
    parse_api_base(&raw)
}

pub fn python_for_bundle(root: &Path) -> Option<std::path::PathBuf> {
    let mut raw = Vec::new();
    std::fs::File::open(root.join("crow-desktop.runtime.json"))
        .ok()?
        .take(16_385)
        .read_to_end(&mut raw)
        .ok()?;
    if raw.len() > 16_384 {
        return None;
    }
    let value: serde_json::Value = serde_json::from_slice(&raw).ok()?;
    if value.get("version")?.as_u64()? != 1 {
        return None;
    }
    let path = std::path::PathBuf::from(
        value
            .get("environment")?
            .get("FAPAI_DESKTOP_PYTHON_PATH")?
            .as_str()?,
    );
    if !path.is_absolute() || !path.is_file() {
        return None;
    }
    Some(path)
}

#[cfg(test)]
mod tests {
    use super::parse_api_base;

    #[test]
    fn direct_launch_uses_the_same_configured_api_as_the_auth_helper() {
        let raw = br#"{"version":1,"environment":{"FAPAI_COLLECTOR_API_BASE":"https://nas.example.invalid/api"}}"#;
        assert_eq!(
            parse_api_base(raw).as_deref(),
            Some("https://nas.example.invalid/api")
        );
        assert_eq!(parse_api_base(b"invalid"), None);
        assert_eq!(parse_api_base(&vec![b' '; 16_385]), None);
    }

    #[test]
    fn rejects_credential_bearing_and_non_api_urls() {
        for api in [
            "-ExecutionPolicy",
            "https://example.invalid\n",
            "file:///secret",
            "https://user:secret@example.invalid",
            "https://example.invalid?key=secret",
            "https://example.invalid/not-api",
        ] {
            let raw =
                serde_json::json!({"version":1,"environment":{"FAPAI_COLLECTOR_API_BASE":api}});
            assert_eq!(parse_api_base(raw.to_string().as_bytes()), None);
        }
    }
}
