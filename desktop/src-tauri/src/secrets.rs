//! Provider settings in the OS keychain. One entry holds a JSON map, so a launch needs one prompt at most.

use std::collections::HashMap;

const SERVICE: &str = "com.zoharbabin.due-diligence-agents";
const ACCOUNT: &str = "provider_env";
const MAX_VALUE: usize = 4096;

/// Must match `SETTABLE_ENV` in `src/dd_agents/api/routers/settings.py`.
/// `tests/unit/test_desktop_drift.py` fails if the two lists differ.
pub const SETTABLE_ENV: &[&str] = &[
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "AWS_PROFILE",
    "AWS_REGION",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_BEARER_TOKEN_BEDROCK",
    "ANTHROPIC_VERTEX_PROJECT_ID",
    "CLOUD_ML_REGION",
];

/// Reject names and values the API would reject. An empty value means "remove".
pub fn validate(values: &HashMap<String, String>) -> Result<(), String> {
    for (name, value) in values {
        if !SETTABLE_ENV.contains(&name.as_str()) {
            return Err(format!("{name} cannot be set here"));
        }
        if value.len() > MAX_VALUE {
            return Err(format!("{name} is too long"));
        }
        if value.chars().any(|c| c.is_control()) {
            return Err(format!("{name} contains control characters"));
        }
    }
    Ok(())
}

/// Apply an update to a map: empty values remove the key.
pub fn merge(
    mut current: HashMap<String, String>,
    update: HashMap<String, String>,
) -> HashMap<String, String> {
    for (name, value) in update {
        if value.is_empty() {
            current.remove(&name);
        } else {
            current.insert(name, value);
        }
    }
    current
}

fn entry() -> Result<keyring::Entry, String> {
    keyring::Entry::new(SERVICE, ACCOUNT).map_err(|e| e.to_string())
}

/// Saved settings. A missing entry or an unreadable keychain gives an empty map, so the app still starts.
pub fn load() -> HashMap<String, String> {
    let Ok(entry) = entry() else {
        return HashMap::new();
    };
    let Ok(text) = entry.get_password() else {
        return HashMap::new();
    };
    let map: HashMap<String, String> = serde_json::from_str(&text).unwrap_or_default();
    map.into_iter()
        .filter(|(k, _)| SETTABLE_ENV.contains(&k.as_str()))
        .collect()
}

pub fn save(update: HashMap<String, String>) -> Result<(), String> {
    validate(&update)?;
    let merged = merge(load(), update);
    let text = serde_json::to_string(&merged).map_err(|e| e.to_string())?;
    entry()?.set_password(&text).map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn map(pairs: &[(&str, &str)]) -> HashMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }

    #[test]
    fn accepts_provider_names() {
        assert!(validate(&map(&[("ANTHROPIC_API_KEY", "sk-1234")])).is_ok());
    }

    #[test]
    fn rejects_other_names() {
        assert!(validate(&map(&[("PATH", "/tmp")])).is_err());
        assert!(validate(&map(&[("LD_PRELOAD", "x")])).is_err());
    }

    #[test]
    fn rejects_control_characters_and_long_values() {
        assert!(validate(&map(&[("ANTHROPIC_API_KEY", "a\nb")])).is_err());
        assert!(validate(&map(&[("ANTHROPIC_API_KEY", &"x".repeat(MAX_VALUE + 1))])).is_err());
    }

    #[test]
    fn empty_value_removes() {
        let out = merge(
            map(&[("AWS_PROFILE", "p"), ("AWS_REGION", "r")]),
            map(&[("AWS_PROFILE", "")]),
        );
        assert_eq!(out, map(&[("AWS_REGION", "r")]));
    }
}
