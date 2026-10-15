//! Secure secret generation and storage (Windows Credential Manager via keyring).

use keyring::Entry;
use rand::RngCore;

const SERVICE: &str = "com.cohenix.pilot";

pub fn generate_secret(bytes: usize) -> String {
    let mut buf = vec![0u8; bytes];
    rand::thread_rng().fill_bytes(&mut buf);
    // URL-safe-ish alphanumeric password without ambiguous punctuation in logs/URLs.
    const ALPHABET: &[u8] = b"ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789";
    buf.into_iter()
        .map(|b| ALPHABET[(b as usize) % ALPHABET.len()] as char)
        .collect()
}

fn entry(key: &str) -> Result<Entry, String> {
    Entry::new(SERVICE, key).map_err(|e| e.to_string())
}

pub fn store_secret(key: &str, value: &str) -> Result<(), String> {
    entry(key)?
        .set_password(value)
        .map_err(|e| e.to_string())
}

pub fn load_secret(key: &str) -> Result<Option<String>, String> {
    match entry(key)?.get_password() {
        Ok(v) => Ok(Some(v)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(e) => Err(e.to_string()),
    }
}

pub fn ensure_install_secrets() -> Result<(String, String, String), String> {
    let admin_ui = match load_secret("admin_ui_password")? {
        Some(v) => v,
        None => {
            let v = generate_secret(24);
            store_secret("admin_ui_password", &v)?;
            v
        }
    };
    let site_admin = match load_secret("site_admin_password")? {
        Some(v) => v,
        None => {
            let v = generate_secret(24);
            store_secret("site_admin_password", &v)?;
            v
        }
    };
    let db_root = match load_secret("db_root_password")? {
        Some(v) => v,
        None => {
            let v = generate_secret(24);
            store_secret("db_root_password", &v)?;
            v
        }
    };
    Ok((admin_ui, site_admin, db_root))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn generated_secrets_are_strong_and_not_samples() {
        let s = generate_secret(24);
        assert_eq!(s.len(), 24);
        assert_ne!(s, "admin");
        assert_ne!(s, "123");
    }
}
