# UI screenshots

Captured from the React UI in **browser mock mode** on Linux
(`npm run preview` + headless Chrome), not from a packaged Windows
`Cohenix-Pilot-Setup.exe` session with real WSL.

| File | Screen |
|---|---|
| `cohenix-pilot-wizard.png` | First-run wizard (preflight) |
| `cohenix-pilot-home.png` | Home dashboard (mock healthy stack) |
| `cohenix-pilot-environments.png` | Environments |
| `cohenix-pilot-settings.png` | Settings |

Reproduce:

```bash
cd desktop/cohenix-pilot
npm run build && npm run preview -- --host 127.0.0.1 --port 4173
# open http://127.0.0.1:4173/?mock=wizard or ?mock=home
```
