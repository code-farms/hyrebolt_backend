# Job Sources

The job-source system is a plugin architecture under `app/sources/`. Every
platform is a `JobSourceConnector` (interface: `get_source_name`,
`search_jobs`, `get_job_details`, `normalize_job`, `health_check`) built by
the `SourceRegistry` from a `JobSourceConfig`. Connectors convert raw source
payloads into the internal `NormalizedJob` model; missing data stays `None` —
never fabricated.

## Compliance rules (non-negotiable)

1. Prefer official APIs, public feeds, and endpoints published for
   consumption.
2. Respect each platform's Terms of Service and robots.txt.
3. Never bypass authentication, CAPTCHA, or anti-bot protection; no stealth
   scraping or fingerprint evasion — ever.
4. A source without a legitimate access path ships as an honest **disabled
   connector** (raises `SourceDisabledError` with the documented reason), not
   a fake implementation.
5. Nothing connects to a real website unless explicitly configured and
   invoked; the test suite runs entirely on local fixtures.

## Source status

| Source | Access method | Auth | Rate limit (self-imposed) | Status | Limitations / notes |
| --- | --- | --- | --- | --- | --- |
| Remote OK (`remoteok`) | Official public JSON API: `GET https://remoteok.com/api` | None | 10/min | **Implemented** | API terms require crediting Remote OK and linking back to the job URL (we store `sourceUrl` for this). Remote-only jobs; salary figures are USD/year. Single feed — filtering is client-side. |
| We Work Remotely (`weworkremotely`) | Public category RSS feeds (default: `remote-programming-jobs.rss`; more via `extra.feeds`) | None | 10/min | **Implemented** | Item titles are `Company: Role`; region granularity is coarse. Remote-only. |
| Company career pages (`company_careers`) | Greenhouse public board API (`boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true`) and Lever public postings API (`api.lever.co/v0/postings/{token}?mode=json`) | None | 30/min | **Implemented** | Boards come from configuration (`extra.boards: [{company, provider, token}]`, empty by default) **plus** every watchlisted company whose `careersUrl` is a recognised Greenhouse/Lever board (Phase 13, merged at search time by `DiscoveryService`). One failing board is skipped; errors only if all fail. Emits `Company.careersUrl` / `metadataSource="company_careers"` — the only startup metadata a board legitimately tells us. Many YC/startup companies are reachable this way. |
| LinkedIn (`linkedin`) | — | Partner-only | — | **Disabled** | Job APIs are gated behind the Talent Solutions partner program; the User Agreement prohibits scraping. TODO: revisit only with partner access. |
| Naukri (`naukri`) | — | Recruiter products only | — | **Disabled** | No public API; terms prohibit automated crawling. |
| Indeed (`indeed`) | — | Partner-only | — | **Disabled** | The public Publisher API was retired; remaining APIs are partner/ATS-gated. |
| Cutshort (`cutshort`) | — | Account-gated | — | **Disabled** | No public API; listings require a signed-in account. |
| Wellfound (`wellfound`) | — | Partner-only | — | **Disabled** | API restricted to ATS/recruiting partners; ToS prohibit scraping. Would also provide Phase 13 startup metadata if partnership is obtained. |
| Y Combinator / Work at a Startup (`ycombinator`) | — | Login-gated | — | **Disabled** | WaaS requires a signed-in account; no public API. Many YC companies are reachable legitimately via `company_careers` (Greenhouse/Lever). |
| Instahyre (`instahyre`) | — | Login-gated | — | **Disabled** | Invite/login-gated matching platform; no public API or feed. |
| Foundit (`foundit`) | — | Recruiter products only | — | **Disabled** | No public API; bot-protected. |

## How enabling works

- Code defaults live in `app/sources/registry.py` (`DEFAULT_CONFIGS`); the
  three implemented connectors are enabled there, stubs are not.
- Operator state is the `JobSource` DB row (seeded all-disabled): the
  discovery engine (Phase 5) merges it over the code default via
  `merge_config` — **DB `enabled` is authoritative**, and a source unknown to
  the DB never runs. Disable a broken source by flipping its row, no deploy
  needed.
- `rateLimitPerMinute` is carried in config now; enforcement plugs into the
  `SourceHTTPClient.throttle` hook when the discovery engine lands (Phase 5).

## Startup metadata (Phase 13)

`NormalizedJob.company` (`CompanyMetadata`: website, careersUrl, industry,
stage, location, description, logoUrl, metadataSource) is optional and every
field is nullable. Persistence (`CompanyRepository.upsert_by_normalized_name`)
only fills `Company` columns that are still null — a later source never
overwrites what an earlier source or the user recorded, and nothing is ever
inferred. Users may edit metadata for companies on their watchlist
(`PATCH /api/v1/companies/{id}`, stamped `metadataSource="user"`).

YC / Work at a Startup, Wellfound and Cutshort would be the natural metadata
sources but remain **disabled** (login-gated / partner-only, see the table):
startups on those platforms are reached through their own Greenhouse/Lever
boards via `company_careers` instead — add the company to your watchlist with
its careers URL and the daily search picks the board up automatically.

## Adding a connector

1. Verify a legitimate access method (official API / published feed) and its
   terms. Document it in the table above.
2. Add `app/sources/connectors/<name>.py` implementing `search_jobs` +
   `normalize_job` (pure, deterministic, no fabricated fields).
3. Register it in `connectors/__init__.py` and `DEFAULT_CONFIGS`; the name
   must match the seeded `JobSource.name`.
4. Add fixture payloads under `tests/sources/fixtures/` and tests following
   `tests/sources/test_remoteok.py`.
