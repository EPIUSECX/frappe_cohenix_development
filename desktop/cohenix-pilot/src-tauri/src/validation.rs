//! Input validation for allowlisted IPC operations.

use regex::Regex;

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum ValidationError {
    #[error("invalid {0}: {1}")]
    Invalid(&'static str, String),
}

pub fn validate_ident(kind: &'static str, value: &str) -> Result<(), ValidationError> {
    let ok = Regex::new(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
        .unwrap()
        .is_match(value);
    if ok {
        Ok(())
    } else {
        Err(ValidationError::Invalid(kind, value.to_string()))
    }
}

pub fn validate_site(value: &str) -> Result<(), ValidationError> {
    let ok = Regex::new(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,126}$")
        .unwrap()
        .is_match(value);
    if ok {
        Ok(())
    } else {
        Err(ValidationError::Invalid("site", value.to_string()))
    }
}

pub fn validate_port(port: u16) -> Result<(), ValidationError> {
    if (1..=65535).contains(&port) {
        Ok(())
    } else {
        Err(ValidationError::Invalid("port", port.to_string()))
    }
}

pub fn validate_profile(value: &str) -> Result<(), ValidationError> {
    match value {
        "frappe" | "erp" | "hr" | "localisation" | "integrations" | "full-cohenix" => Ok(()),
        _ => Err(ValidationError::Invalid("profile", value.to_string())),
    }
}

pub fn validate_https_git_url(value: &str) -> Result<(), ValidationError> {
    let ok = value.starts_with("https://")
        && !value.contains(' ')
        && !value.contains(';')
        && !value.contains('|')
        && !value.contains('`')
        && value.len() < 512;
    if ok {
        Ok(())
    } else {
        Err(ValidationError::Invalid("url", value.to_string()))
    }
}

pub fn validate_stage(value: &str) -> Result<(), ValidationError> {
    match value {
        "preflight"
        | "wsl_enable"
        | "distro"
        | "linux_deps"
        | "pilot_install"
        | "cohenix_provision"
        | "verify"
        | "ready"
        | "advance_preflight"
        | "advance_wsl"
        | "system_deps"
        | "start"
        | "all" => Ok(()),
        _ => Err(ValidationError::Invalid("stage", value.to_string())),
    }
}

/// Redact common secret patterns from log lines before UI display.
pub fn redact_line(line: &str) -> String {
    let patterns = [
        (r"(?i)(password[=:\s]+)\S+", "${1}***"),
        (r"(?i)(passwd[=:\s]+)\S+", "${1}***"),
        (r"(?i)(token[=:\s]+)\S+", "${1}***"),
        (r"(?i)(secret[=:\s]+)\S+", "${1}***"),
        (r"(sid=)[^&\s]+", "${1}***"),
    ];
    let mut out = line.to_string();
    for (pat, rep) in patterns {
        let compiled = Regex::new(pat).unwrap();
        out = compiled.replace_all(&out, rep).into_owned();
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_default_distro_and_site() {
        validate_ident("distro", "Cohenix-Pilot").unwrap();
        validate_site("cohenix.localhost").unwrap();
        validate_profile("hr").unwrap();
        validate_port(8000).unwrap();
    }

    #[test]
    fn rejects_shell_metacharacters() {
        assert!(validate_ident("distro", "x;rm -rf").is_err());
        assert!(validate_site("evil $(reboot)").is_err());
        assert!(validate_https_git_url("http://insecure").is_err());
        assert!(validate_profile("../../etc").is_err());
        assert!(validate_stage("rm -rf").is_err());
    }

    #[test]
    fn redacts_passwords() {
        let line = redact_line("admin-password=hunter2 and sid=abc123&x=1");
        assert!(!line.contains("hunter2"));
        assert!(!line.contains("abc123"));
        assert!(line.contains("***"));
    }
}
