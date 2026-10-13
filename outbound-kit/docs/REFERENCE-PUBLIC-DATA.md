# Public-data reference audit

This note separates three different capabilities that should not be presented as one
"public procurement monitor": catalog discovery, G2B order-plan retrieval, and DART corporate
disclosures. The repositories were inspected read-only; no package, skill, proxy, daemon, API
key, or global dependency was installed.

## Sources and provenance

| Source | Inspected revision | License | Files used for the decision |
|---|---|---|---|
| `Wendy-Nam/public-data-lens` | `8886dcd2b1c69e4a965b1fb331f9543ba18a2013` (2026-08-05) | MIT, copyright 2026 HIKE Lab | `README.md`, `LICENSE`, `DESIGN.md`, `docs/개인정보_로그_고지_v1.1.md`, ADR-008, `apps/server/datanav/api/mcp_server.py`, `api/usage.py`, tool schemas |
| `NomaDamas/k-skill` | `50d7bb30f9e2d6b8b09da1055d497fe616820e30` (2026-10-08) | repository MIT; inspected skill manifests and D2B/S2B packages declare MIT | `g2b-order-plan-search`, `g2b-sanctioned-supplier`, `d2b-notice-search`, `s2b-notice-search`, `k-dart`, `company-analysis`, and `job-posting-match` manifests/instructions plus relevant helpers, package sources, source contract, and legal disclaimer |
| `NousResearch/hermes-agent` v0.21.7 source | `71d34bad1045610252eda02ee79549436896e784` (2026-10-11) | MIT, copyright 2025 Nous Research | `nix/moduleCommon.nix`, `tools/mcp_tool_transport.py`, `tools/mcp_tool_registration.py` confirm HTTP headers, timeouts, tool include filters, and strict redirect-header handling |

No personal-repository data, credentials, DART key, data.go.kr key, hosted-proxy configuration,
or private query was read. A query-free MCP `probe` was attempted from this Linux cloud workspace
on 2026-10-13 with ambient proxies disabled and failed at the transport boundary; no live tool or
result is therefore verified. MIT permits reuse with its notice, but this kit does not copy donor
code: it records contracts and implements a small independent Hermes connector.

## What Public Data Lens actually does

The hosted endpoint documented by the donor is:

```text
https://service.datahub.kr/projects/public-data-lens/mcp
```

It is an unauthenticated, read-only MCP over the public-data-portal **monthly catalog**. Its
tools search catalog metadata, compare catalog records, show monthly catalog changes/statistics,
search observed column names, retrieve gated structure observations, and construct a
deterministic `DRAFT` data-use plan. Responses carry evidence labels such as
`CATALOG_METADATA_ONLY`, `FILE_OBSERVATION`, `DRAFT`, and `CANDIDATE_ONLY`.

That makes it useful for questions such as "which official dataset might contain procurement
notices or business information?" It does **not** establish that a current tender exists, fetch
the notice/attachment, track corrections, determine eligibility, or submit a bid. A catalog hit
for a G2B dataset is discovery evidence, not a procurement record.

The README badge says the frozen v1.0 contract has additive changes through v1.6, while the
inspected tree contains schemas through v1.8 and v1.8-specific family-candidate code. The helper
therefore pins the endpoint and a least-privilege tool-name allowlist, not a claim about the
currently deployed schema version. A live `probe` verifies only MCP initialization and tool
discovery.

### Privacy contract

The hosted service normally records anonymous usage fields and may record the raw search or
purpose text, capped at 200 characters, for up to 12 months. It says it does not store raw IP or
raw User-Agent. DNT, GPC, or `X-Datanav-No-Log: 1` opts the request out of all usage logging.
The server implementation checks that header in `api/usage.py` and skips `_log_usage`.

The kit always configures `X-Datanav-No-Log: 1`, uses Hermes 0.21.7's
`strict_redirect_headers=true`, and exposes only the nine inspected read-only tools. Users must
still avoid names, phone numbers, unreleased strategies, customer lists, or other private text in
public catalog queries: a remote service and network path remain involved, and the no-log header
does not make private disclosure appropriate.

The donor advertises a beta service without SLA and a fair-use limit of 2 requests/second per IP
with a burst of 20. This kit adds no scheduler or bulk crawler for it.

## Implemented optional Hermes connector

`public_data_lens.py` is deliberately independent of the workshop's required path:

```sh
python3 public_data_lens.py plan  --home ~/.hermes-outbound
python3 public_data_lens.py apply --home ~/.hermes-outbound
python3 public_data_lens.py check --home ~/.hermes-outbound
python3 public_data_lens.py probe --home ~/.hermes-outbound
```

`apply` additively writes `mcp_servers.public-data-lens` under a cross-platform advisory lock with the fixed HTTPS endpoint, no-log
header, strict redirect-header policy, explicit tool allowlist, and timeouts. It preserves all
unrelated model/channel/MCP settings and refuses an existing conflicting server entry or unknown
`mcp_servers` shape. No secret is needed. The gateway must be restarted afterward.

`probe` disables ambient proxies and redirects, sends the no-log header on `initialize`,
`notifications/initialized`, and `tools/list`, bounds responses to 2 MiB, and sends no catalog
query. It also requires `readOnlyHint=true` and `destructiveHint=false` on every allowlisted tool.
Passing it means connector discovery works; it leaves `functional_verified=false` and
`procurement_notice_verified=false`. A useful catalog query remains a separate, user-reviewed
action.

## k-skill procurement reference

`g2b-order-plan-search` calls data.go.kr dataset `15129462`,
`OrderPlanSttusService`, through `GET /v1/g2b/order-plans` on a hosted or self-hosted
`k-skill-proxy`. The data.go.kr key stays on that proxy. It supports goods, construction,
services, and foreign-procurement **order plans** and may return `bidNtceNoList` when upstream
provides it.

Hard boundary:

- an order plan is an advance plan, not an actual pre-specification, bid notice, award, or
  contract;
- a linked notice number is not the current notice text, correction history, attachments, or
  eligibility proof;
- participation requires the final official notice and attachments, notice number/revision,
  dates, region, licenses/industry codes, performance, registrations, and other requirements;
- no login, certificate, bid submission, payment, award, or contract action is implemented.

The donor helper defaults to `https://k-skill-proxy.nomadamas.org`. Using it would introduce an
external operator and availability/trust boundary. No live proxy call or key-approval check was
performed here. It should not be bundled or advertised until the specific hosted-proxy terms,
response shape, rate behavior, and a disposable end-to-end call are reviewed. If later adopted,
its records must be labeled `procurement_order_plan`, never `tender_notice`.

### Other procurement surfaces are separate products

The related donor skills do not close that G2B notice gap:

| Donor reference | What it actually exposes | Integration decision |
|---|---|---|
| `g2b-sanctioned-supplier` | Exact ten-digit business-number lookup of **currently active** participation restrictions through hosted/self-hosted `k-skill-proxy`; expired/released history and unregistered entities are outside coverage | Not integrated. It is supplier due diligence, not notice discovery or eligibility proof. A zero result must not become "eligible." The business number goes to an external proxy unless self-hosted. |
| `d2b-notice-search` / package `0.2.1` | Actual public Defense e-Procurement notice candidates from the rendered D2B form; normal/urgent/correction/cancel/postponed/rebid filters and at most a 12-month window | Not integrated or live-tested. Primary route requires a supported interactive browser runtime; direct JSON is explicitly best-effort and can return security-routing HTML. It does not log in, bid, sign, or submit. |
| `s2b-notice-search` / package `0.2.1` | Actual public S2B school-marketplace notices/quote requests through a browser/session-aware form; list/detail fixture parsers and at most a three-calendar-month window | Not integrated or live-tested. A valid rendered session/form is part of the contract; empty HTML can be a session failure rather than no results. It does not quote, bid, contract, or log in. |

Therefore `D2B/S2B notice candidate`, `G2B order plan`, `active sanction lookup`, and `final
official notice` are four different record types. Even a real D2B/S2B candidate still requires
the current detail page, correction state, attachments, dates, and participation requirements to
be reviewed before any eligibility or outreach decision.

## k-skill DART reference

`k-dart` describes direct, read-only calls to `https://opendart.fss.or.kr/api/` for disclosures,
company profiles, financial statements, employee counts, and material-event reports. It requires
the user's `API_K_DART` key and usually an eight-digit `corp_code`. DART can be an independent
company/outbound signal, but it is neither Public Data Lens nor public procurement.

The inspected skill is instruction-only and its shell examples place the expanded API key in
curl arguments/query parameters. That can expose a key in process inspection, shell tracing, or
support transcripts. The kit therefore does not vendor or auto-run it. A future adapter would
need private terminal input or `.env` storage, fixed-origin requests, disabled redirects and
ambient proxies, bounded responses, status/rate-limit handling, and fully redacted errors.

`company-analysis` is a different, heavier workflow. It deliberately avoids the OpenDART API key
and captures public DART/KIND/issuer pages into immutable local snapshots with hashes, quotes,
filing IDs, period/unit/scope checks, and separate income/balance-sheet/cash-flow treatment. That
could support a reviewed company signal, but it is not a lightweight DART lookup and was not
vendored or executed. Its public-page and price-provider availability still needs live validation.

## k-skill job-posting reference

`job-posting-match` searches public JobKorea and Saramin result pages for a **job seeker's**
resume-to-posting match. It contains useful query-normalization and conservative-evidence ideas,
but the donor's required legal boundary limits automation to personal, non-organizational lookup
and explicitly forbids systematic/bulk crawling and database building. It also processes resume
text, which can carry phone, email, address, and other personal data.

That contract conflicts with a recurring outbound company-sourcing cron. The kit does not vendor
or invoke it. For this workshop, use the kit's bounded public-ATS source or a user-supplied export;
do not repurpose the donor job-seeker workflow into organization-scale sales prospecting. Never
send resume text to Public Data Lens or another remote catalog/search connector.

## Workshop decision

| Workshop promise | Current status |
|---|---|
| Discover relevant public datasets | Optional connector implemented; synthetic tests only, live endpoint unverified |
| Search G2B order plans | Donor reference audited; not integrated or live-verified |
| Look up currently active G2B sanctions | Donor reference audited; not integrated; not eligibility proof |
| Search actual public D2B/S2B notice candidates | Donor browser recipes audited; not integrated or live-verified |
| Monitor actual tender notices and corrections | Missing; do not claim |
| Determine bid eligibility | Human review of final official notice and company evidence required |
| DART corporate signal | Donor reference audited; not integrated because credential-safe adapter is absent |
| Recurring JobKorea/Saramin sales sourcing | Rejected: donor's personal-lookup boundary conflicts with bulk/organizational use |

For the immediate workshop, Public Data Lens can be an optional discovery exercise. The tender
workflow should remain official-export/file mode until a separate current-notice adapter is
implemented and tested. Never turn catalog metadata or an order plan into an outbound contact or
eligibility decision without source-specific verification and human approval.
