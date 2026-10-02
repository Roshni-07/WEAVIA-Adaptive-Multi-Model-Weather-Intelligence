# Data, Privacy and Intended Use

Plain-language notice for WEAVIA. It is not legal advice.

## Intended use

WEAVIA is a **research and demonstration prototype** built for Smart India Hackathon 2026 (SIH26081, Ministry of Earth Sciences).

- All forecasts, weights and verification figures come from a **synthetic** multi-model world.
- **Do not use it to make real weather, safety or disaster-response decisions.** It is not an official forecast and carries no warranty. For real warnings, use the India Meteorological Department.
- Results validate the software. They are not evidence of skill on real weather. See [VERIFICATION.md](VERIFICATION.md).

## What the application collects

| Item | Collected? |
|---|---|
| Accounts, logins, emails | No. There are none |
| Cookies | No |
| Browser storage (localStorage / sessionStorage) | No. Interface state lives in the URL |
| Analytics or tracking scripts | No |
| Third-party requests from the browser | No. Fonts are self-hosted |
| Personal data | None is requested or stored |

The hosting provider may keep ordinary server logs (IP address, time, path). The API applies a per-client rate limit held in memory only, and discarded after a minute.

Because the app sets no cookies and runs no tracking, a cookie-consent banner is not needed. **If analytics or any tracking is added later, add consent handling and update this page first.**

## Third-party data (when real data is added)

Real-data sources will have their own licences and attribution rules (for example, Open-Meteo data is CC BY 4.0). They will be listed here and in the README before the first real-data release.

## Software licence

MIT. See [LICENSE](../LICENSE).

## Contact and reports

Use GitHub Issues on this repository. Security problems: see [SECURITY.md](../SECURITY.md).
