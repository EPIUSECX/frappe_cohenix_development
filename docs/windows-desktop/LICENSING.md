# Licensing notes for Cohenix Pilot (Windows)

## Upstream Frappe Pilot (AGPL-3.0)

[Frappe Pilot](https://github.com/frappe/pilot) is licensed under the GNU Affero
General Public License v3.0 (AGPL-3.0).

Implications for this product:

1. **Orchestration vs redistribution**  
   Cohenix Pilot downloads a pinned Pilot release into the user's WSL home
   directory at install time. That is redistribution of the upstream release
   tarball to the end user. Preserve Pilot's license and copyright notices.
   Do not strip `license.txt` from the extracted tree.

2. **Modifying Pilot**  
   If Cohenix ships patches or a fork of Pilot, the modified Pilot (and any
   larger work that constitutes a combined AGPL-covered program) must be offered
   under AGPL-3.0 with corresponding source. Prefer upstream releases over
   forks unless there is a documented need.

3. **Network use**  
   AGPL §13 requires offering corresponding source to users who interact with a
   modified version over a network. Pilot Admin is a local loopback service in
   the default Cohenix Pilot configuration; treat any LAN exposure as in-scope
   for compliance review.

4. **Windows app license**  
   The Tauri/React host application source in `desktop/cohenix-pilot/` should be
   released under a license compatible with the repository's overall terms.
   Linking against or shelling out to Pilot does not by itself force the Windows
   UI to be AGPL, but embedding Pilot's Admin UI or bundling Pilot binaries
   inside the installer requires a legal review before production distribution.

5. **Before production signing / public download**  
   Confirm with counsel: installer contents, whether Pilot is bundled vs
   downloaded, and source-offer URLs for any AGPL components.

## Frappe / ERPNext / HRMS

Frappe Framework and related apps have their own licenses (typically GPL-3.0 for
Frappe/ERPNext). Site source under `~/pilot/benches/` remains subject to those
licenses. Cohenix Pilot does not relicense those apps.
