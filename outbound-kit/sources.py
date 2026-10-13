#!/usr/bin/env python3
"""Bounded, read-only source adapters for Hermes Outbound Kit.

The adapters never log in, submit forms, write to a CRM, or bypass an
access-control response. They ignore ambient proxies; a caller may inject only
an explicitly reviewed source-scoped transport. Every command prints one JSON envelope so an
upstream workflow can distinguish a valid empty result from a blocked or broken
source.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import html
import io
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable
import urllib.error
import urllib.parse
import urllib.request


SCHEMA_VERSION = "outbound-source/v1"
STATUSES = {"ok", "empty", "blocked", "failed", "invalid_response"}
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
USER_AGENT = "Hermes-Outbound-Kit/0.1 (+https://github.com/Wendy-Nam/hermes-outbound-kit)"
WP_ENDPOINT = "https://platum.kr/wp-json/wp/v2/posts"
WANTED_ENDPOINT = "https://www.wanted.co.kr/api/chaos/search/v1/results"
SARAMIN_ENDPOINT = "https://www.saramin.co.kr/zf_user/search/recruit"

# Public-source contract references (MIT, Wendy Nam, 2026), inspected at
# hermes-agent-kit commit 76e15170a2dc8b2bce270bd50e07287a14c3dd6b:
# bundle/job-search/skills/job-search/wanted-search/scripts/wanted_search.py
# bundle/job-search/skills/job-search/kr-search/scripts/kr_job_search.py
# This module is a bounded adaptation: it does not copy the donor's personal
# seniority filters or its job-collect proxy/rotation orchestration.


@dataclass
class SourceResult:
    status: str
    source: str
    records: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown source status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256(value: Any) -> str:
    raw = value if isinstance(value, bytes) else canonical_json(value)
    return hashlib.sha256(raw).hexdigest()


def clean_text(value: Any) -> str:
    text = value if isinstance(value, str) else ""
    text = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def normalize_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # Lever commonly returns epoch milliseconds.
        seconds = float(value) / 1000 if value > 10_000_000_000 else float(value)
        try:
            return datetime.fromtimestamp(seconds, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.isoformat()
        return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except ValueError:
        return None


def canonical_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        parsed = urllib.parse.urlsplit(text)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(k, v) for k, v in query if not (k.lower().startswith("utm_") or k.lower() in {"fbclid", "gclid"})]
    query.sort()
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, urllib.parse.urlencode(query), ""))


def source_id_from_url(source: str, url: str, supplied: Any = None) -> str:
    if supplied is not None and str(supplied).strip():
        return re.sub(r"\s+", " ", str(supplied)).strip()[:200]
    patterns = (
        ("wanted", r"wanted\.co\.kr/wd/(\d+)"),
        ("saramin", r"[?&]rec_idx=(\d+)"),
        ("jobkorea", r"/GI_Read/(\d+)"),
        ("linkedin", r"/jobs/view/(?:[^/?]*?-)?(\d+)(?:[/?]|$)"),
    )
    lower = source.lower()
    for label, pattern in patterns:
        match = re.search(pattern, url, re.I)
        if match and (label in lower or label in url.lower()):
            return f"{label}:{match.group(1)}"
    return "url:" + sha256(url.encode("utf-8"))[:24]


def evidence(source: str, source_id: str, url: str, retrieved_at: str, raw: Any) -> dict[str, str]:
    return {
        "source": source,
        "url": url,
        "source_id": source_id,
        "retrieved_at": retrieved_at,
        "raw_sha256": sha256(raw),
    }


def _read_limited(response: Any) -> bytes:
    raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError(f"response exceeded {MAX_RESPONSE_BYTES} bytes")
    return raw


def fetch_json(url: str, source: str, timeout: int = 20, *, opener=None) -> tuple[str, Any, str | None]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args: Any, **kwargs: Any) -> None:
            return None
    try:
        # Default live adapters ignore ambient proxy variables. A reviewed,
        # source-scoped transport (for example runtime_connect.webshare_fetch)
        # may inject an opener explicitly; callers remain responsible for its
        # exact-origin contract.
        transport = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect)
        with transport.open(request, timeout=timeout) as response:
            raw = _read_limited(response)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 429):
            return "blocked", None, f"{source}: HTTP {exc.code}; access denied or rate limited. Do not retry with a proxy."
        return "failed", None, f"{source}: HTTP {exc.code}; source request failed."
    except urllib.error.URLError as exc:
        return "failed", None, f"{source}: network failure: {exc.reason}"
    except (TimeoutError, OSError) as exc:
        return "failed", None, f"{source}: network failure: {type(exc).__name__}"
    except ValueError as exc:
        return "invalid_response", None, f"{source}: {exc}"
    try:
        return "ok", json.loads(raw.decode("utf-8-sig")), None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "invalid_response", None, f"{source}: response was not valid JSON"


def fetch_bytes(url: str, source: str, timeout: int = 20, *, opener=None) -> tuple[str, bytes | None, str | None]:
    """Fetch one bounded public document without redirects or access bypass."""
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
    })

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args: Any, **kwargs: Any) -> None:
            return None

    try:
        transport = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect)
        with transport.open(request, timeout=timeout) as response:
            return "ok", _read_limited(response), None
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 429):
            return "blocked", None, f"{source}: HTTP {exc.code}; access denied or rate limited. Do not retry with a proxy."
        return "failed", None, f"{source}: HTTP {exc.code}; source request failed."
    except urllib.error.URLError as exc:
        return "failed", None, f"{source}: network failure: {exc.reason}"
    except (TimeoutError, OSError) as exc:
        return "failed", None, f"{source}: network failure: {type(exc).__name__}"
    except ValueError as exc:
        return "invalid_response", None, f"{source}: {exc}"


def load_fixture(path: str) -> tuple[str, Any, str | None]:
    try:
        raw = Path(path).read_bytes()
        if len(raw) > MAX_RESPONSE_BYTES:
            return "invalid_response", None, f"fixture exceeded {MAX_RESPONSE_BYTES} bytes"
        return "ok", json.loads(raw.decode("utf-8-sig")), None
    except OSError as exc:
        return "failed", None, f"fixture read failed: {exc}"
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "invalid_response", None, "fixture was not valid JSON"


FUND_EVENT = re.compile(
    r"펀드\s*(?:결성|조성)|투자\s*조합|모태\s*펀드|출자\s*(?:사업|공고)|재원\s*조성|fund\s*(?:formation|launch)",
    re.I,
)
FUNDING_EVENT = re.compile(r"투자\s*유치|투자를?\s*받|펀딩\s*(?:유치|완료)|(?:pre[- ]?|series\s*)[a-d]\s*(?:투자|라운드)|시리즈\s*[a-d]\s*(?:투자|라운드)", re.I)
ROUND = re.compile(r"(?:시리즈\s*[A-D]|프리\s*[A-B]|시드|브릿지|Pre[- ]?[A-B]|Series\s*[A-D])", re.I)
AMOUNT = re.compile(r"\b\d[\d,]*(?:\.\d+)?\s*(?:억|조)\s*원?", re.I)
QUOTED_COMPANY = re.compile(r"[‘'\"“]([^’'\"”]{2,40})[’'\"”]")
GENERIC_COMPANY = re.compile(r"(?:스타트업|기업|플랫폼|서비스|솔루션|업체|개발사)$")
INVESTOR_SUFFIX = re.compile(r"(?:벤처스|파트너스|캐피탈|인베스트먼트|자산운용|프라이빗에쿼티|액셀러레이터)$", re.I)
SECTORS = (
    ("AI", re.compile(r"\bAI\b|인공지능|에이전트|\bLLM\b|딥러닝", re.I)),
    ("health", re.compile(r"바이오|헬스|의료|제약|진단|병원", re.I)),
    ("fintech", re.compile(r"핀테크|금융|결제|보험|대출|송금", re.I)),
    ("commerce", re.compile(r"커머스|이커머스|리테일|브랜드|뷰티|패션", re.I)),
    ("robotics", re.compile(r"로보틱스|로봇|자율주행|모빌리티|드론", re.I)),
    ("B2B/SaaS", re.compile(r"\bSaaS\b|\bB2B\b|솔루션|자동화|인프라", re.I)),
)


def funding_company_candidate(title: str) -> tuple[str | None, str]:
    quoted = QUOTED_COMPANY.search(title)
    if quoted:
        return clean_text(quoted.group(1))[:80] or None, "medium"
    prefix = re.split(r"[,·]|\s[-—]\s|…", title, maxsplit=1)[0].strip(" ,·'\"‘’“”")
    prefix = re.sub(r"^(?:단독|종합|인터뷰)\s*[:：-]?\s*", "", prefix)
    if not prefix or len(prefix) > 80 or GENERIC_COMPANY.search(prefix):
        return prefix[:80] or None, "low" if prefix else "unknown"
    return prefix, "low"


def funding_sector(text: str) -> str | None:
    for name, pattern in SECTORS:
        if pattern.search(text):
            return name
    return None


def normalize_funding_posts(payload: Any, retrieved_at: str, source: str = "platum-wordpress", limit: int = 20) -> SourceResult:
    if not isinstance(payload, list):
        return SourceResult("invalid_response", source, errors=["WordPress response must be a JSON list"])
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    excluded = 0
    seen: set[str] = set()
    for index, post in enumerate(payload[:limit]):
        if not isinstance(post, dict):
            errors.append(f"row {index}: expected object")
            continue
        title = clean_text((post.get("title") or {}).get("rendered") if isinstance(post.get("title"), dict) else post.get("title"))
        excerpt = clean_text((post.get("excerpt") or {}).get("rendered") if isinstance(post.get("excerpt"), dict) else post.get("excerpt"))
        blob = f"{title} {excerpt}".strip()
        if not title:
            continue
        if FUND_EVENT.search(blob):
            excluded += 1
            continue
        if not FUNDING_EVENT.search(blob):
            continue
        url = canonical_url(post.get("link"))
        if not url:
            errors.append(f"row {index}: missing valid public URL")
            continue
        candidate, confidence = funding_company_candidate(title)
        if candidate and INVESTOR_SUFFIX.search(candidate):
            # An investor-named subject may itself have raised capital, but the
            # title alone is not enough to call it a startup funding event.
            confidence = "low"
        native = post.get("id")
        sid = f"wp:{native}" if native is not None and str(native).strip() else source_id_from_url(source, url)
        dedupe_key = f"{source}:{sid}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        amounts = list(dict.fromkeys(x.replace(" ", "") for x in AMOUNT.findall(blob)))
        rounds = list(dict.fromkeys(clean_text(x) for x in ROUND.findall(blob)))
        record = {
            "schema_version": SCHEMA_VERSION,
            "record_type": "funding_signal",
            "source": source,
            "source_id": sid,
            "company": None,
            "company_candidate": candidate,
            "company_confidence": confidence,
            "title": title,
            "url": url,
            "published_at": normalize_date(post.get("date")),
            "stack": None,
            "round_candidate": rounds[0] if len(rounds) == 1 else None,
            "amount_candidate": amounts[0] if len(amounts) == 1 else None,
            "amount_candidates": amounts,
            "sector_candidate": funding_sector(blob),
            "review_required": confidence != "medium" or len(amounts) != 1,
            "evidence": evidence(source, sid, url, retrieved_at, post),
        }
        records.append(record)
    status = "ok" if records else ("invalid_response" if errors else "empty")
    return SourceResult(status, source, records, errors, {"excluded_fund_events": excluded})


def collect_funding(pages: int, per_page: int, fixture: str | None, retrieved_at: str) -> SourceResult:
    source = "platum-wordpress"
    if fixture:
        status, payload, error = load_fixture(fixture)
        if status != "ok":
            return SourceResult(status, source, errors=[error or "fixture failed"])
        return normalize_funding_posts(payload, retrieved_at, source, per_page * pages)
    all_posts: list[Any] = []
    for page in range(1, pages + 1):
        query = urllib.parse.urlencode({
            "categories": 7521,
            "per_page": per_page,
            "page": page,
            "_fields": "id,title,link,date,excerpt",
        })
        status, payload, error = fetch_json(f"{WP_ENDPOINT}?{query}", source)
        if status != "ok":
            return SourceResult(status, source, errors=[error or "funding source failed"], metadata={"page": page})
        if not isinstance(payload, list):
            return SourceResult("invalid_response", source, errors=[f"page {page}: expected a JSON list"])
        if not payload:
            break
        all_posts.extend(payload)
    return normalize_funding_posts(all_posts, retrieved_at, source, pages * per_page)


ALIASES = {
    "company": ("company", "company_name", "회사", "회사명"),
    "title": ("title", "position", "job_title", "포지션", "공고명", "직무"),
    "url": ("url", "link", "링크", "공고url", "공고_url"),
    "published_at": ("published_at", "date", "posted_at", "게시일", "등록일", "발견"),
    "stack": ("stack", "skills", "tech_stack", "기술스택", "스택"),
    "source": ("source", "board", "보드"),
    "source_id": ("source_id", "posting_id", "id", "공고id"),
    "location": ("location", "근무지", "지역"),
}


def _lookup(row: dict[str, Any], field_name: str) -> Any:
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for alias in ALIASES[field_name]:
        if alias.lower() in lowered:
            return lowered[alias.lower()]
    return None


def normalize_stack(value: Any) -> list[str] | None:
    if value is None or value == "":
        return None
    if isinstance(value, list):
        items = [clean_text(v) for v in value]
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                items = [clean_text(v) for v in parsed] if isinstance(parsed, list) else [text]
            except json.JSONDecodeError:
                items = re.split(r"[,;|]", text)
        else:
            items = re.split(r"[,;|]", text)
    else:
        return None
    cleaned = [item.strip() for item in items if item and item.strip()]
    return list(dict.fromkeys(cleaned)) or None


def read_job_rows(path: str, format_name: str = "auto") -> tuple[str, list[Any] | None, str | None]:
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        return "failed", None, f"job file read failed: {exc}"
    if len(raw) > MAX_RESPONSE_BYTES:
        return "invalid_response", None, f"job file exceeded {MAX_RESPONSE_BYTES} bytes"
    fmt = format_name
    if fmt == "auto":
        fmt = "csv" if Path(path).suffix.lower() == ".csv" else "json"
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return "invalid_response", None, "job file must be UTF-8 or UTF-8 with BOM"
    if fmt == "csv":
        try:
            reader = csv.DictReader(io.StringIO(text))
            if not reader.fieldnames:
                return "invalid_response", None, "CSV has no header row"
            return "ok", list(reader), None
        except csv.Error as exc:
            return "invalid_response", None, f"CSV parse failed: {exc}"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return "invalid_response", None, f"JSON parse failed at line {exc.lineno}"
    if isinstance(data, dict):
        data = data.get("records", data.get("items", data.get("postings")))
    if not isinstance(data, list):
        return "invalid_response", None, "job JSON must be a list or contain records/items/postings"
    return "ok", data, None


def normalize_job_rows(rows: Iterable[Any], retrieved_at: str, source_default: str = "user-file") -> SourceResult:
    rows = list(rows)
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    source_names: set[str] = set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            errors.append(f"row {index}: expected object")
            continue
        title = clean_text(_lookup(raw, "title"))
        url = canonical_url(_lookup(raw, "url"))
        if not title or not url:
            errors.append(f"row {index}: title and public http(s) URL are required")
            continue
        company = clean_text(_lookup(raw, "company")) or None
        source = clean_text(_lookup(raw, "source")) or source_default
        sid = source_id_from_url(source, url, _lookup(raw, "source_id"))
        key = f"{source.lower()}:{sid}"
        if key in seen:
            continue
        seen.add(key)
        source_names.add(source)
        record = {
            "schema_version": SCHEMA_VERSION,
            "record_type": "job_posting",
            "source": source,
            "source_id": sid,
            "company": company,
            "company_candidate": company,
            "company_confidence": "provided" if company else "unknown",
            "title": title,
            "url": url,
            "published_at": normalize_date(_lookup(raw, "published_at")),
            "stack": normalize_stack(_lookup(raw, "stack")),
            "location": clean_text(_lookup(raw, "location")) or None,
            "review_required": company is None,
            "evidence": evidence(source, sid, url, retrieved_at, raw),
        }
        records.append(record)
    status = "ok" if records else ("invalid_response" if errors else "empty")
    label = source_default if not source_names else (next(iter(source_names)) if len(source_names) == 1 else "mixed-job-import")
    return SourceResult(status, label, records, errors, {
        "duplicates_removed": max(0, len(rows) - len(records) - len(errors))
    })


def import_jobs(path: str, format_name: str, retrieved_at: str) -> SourceResult:
    status, rows, error = read_job_rows(path, format_name)
    if status != "ok":
        return SourceResult(status, "job-import", errors=[error or "job import failed"])
    return normalize_job_rows(rows or [], retrieved_at)


def normalize_wanted(payload: Any, query: str, retrieved_at: str, limit: int = 20) -> SourceResult:
    """Normalize the public Wanted search response without job-seeker filters."""
    source = "wanted-public-search"
    if not isinstance(payload, dict) or "positions" not in payload:
        return SourceResult("invalid_response", source, errors=[
            "Wanted response must be an object with a positions field"
        ], metadata={"query": query})
    positions = payload["positions"]
    if isinstance(positions, dict):
        if isinstance(positions.get("data"), list):
            positions = positions["data"]
        elif isinstance(positions.get("list"), list):
            positions = positions["list"]
        else:
            return SourceResult("invalid_response", source, errors=[
                "Wanted positions wrapper must contain a data or list array"
            ], metadata={"query": query})
    if not isinstance(positions, list):
        return SourceResult("invalid_response", source, errors=[
            "Wanted positions must be an array"
        ], metadata={"query": query})
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(positions[:limit]):
        if not isinstance(raw, dict):
            errors.append(f"row {index}: expected object")
            continue
        native_id = raw.get("id")
        title = clean_text(raw.get("position") or raw.get("title") or raw.get("name"))
        if native_id is None or not str(native_id).strip() or not title:
            errors.append(f"row {index}: id and title are required")
            continue
        native_id = str(native_id).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", native_id):
            errors.append(f"row {index}: invalid id")
            continue
        sid = f"wanted:{native_id}"
        if sid in seen:
            continue
        seen.add(sid)
        company_value = raw.get("company")
        company = clean_text(company_value.get("name") if isinstance(company_value, dict)
                             else raw.get("company_name") or company_value) or None
        address = raw.get("address")
        location = clean_text(address.get("location") if isinstance(address, dict)
                              else raw.get("location")) or None
        url = f"https://www.wanted.co.kr/wd/{urllib.parse.quote(native_id, safe='')}"
        records.append({
            "schema_version": SCHEMA_VERSION, "record_type": "job_posting",
            "source": source, "source_id": sid,
            "company": company, "company_candidate": company,
            "company_confidence": "public_listing" if company else "unknown",
            "title": title, "url": url, "published_at": None,
            "stack": None, "location": location,
            "review_required": company is None,
            "evidence": evidence(source, sid, url, retrieved_at, raw),
        })
    status = "ok" if records else ("invalid_response" if errors else "empty")
    return SourceResult(status, source, records, errors, {
        "query": query, "returned_positions": len(positions), "bounded_limit": limit,
    })


def collect_wanted(query: str, limit: int, fixture: str | None, retrieved_at: str) -> SourceResult:
    source = "wanted-public-search"
    if fixture:
        status, payload, error = load_fixture(fixture)
    else:
        encoded = urllib.parse.urlencode({"query": query, "limit": limit})
        status, payload, error = fetch_json(f"{WANTED_ENDPOINT}?{encoded}", source, timeout=15)
    if status != "ok":
        return SourceResult(status, source, errors=[error or "Wanted source failed"],
                            metadata={"query": query})
    return normalize_wanted(payload, query, retrieved_at, limit)


SARAMIN_EMPTY = re.compile(r"검색\s*결과가\s*없|채용정보가\s*없|검색된\s*공고가\s*없")


def normalize_saramin_html(raw: bytes | str, query: str, retrieved_at: str,
                           limit: int = 20) -> SourceResult:
    source = "saramin-public-search"
    try:
        page = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    except UnicodeDecodeError:
        return SourceResult("invalid_response", source, errors=["Saramin response was not UTF-8"],
                            metadata={"query": query})
    blocks = page.split('class="item_recruit"')[1:]
    if not blocks:
        if SARAMIN_EMPTY.search(clean_text(page)):
            return SourceResult("empty", source, metadata={"query": query, "bounded_pages": 1})
        return SourceResult("invalid_response", source, errors=[
            "Saramin page had neither recognized result blocks nor an explicit empty-result marker"
        ], metadata={"query": query, "bounded_pages": 1})
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for index, block in enumerate(blocks):
        if len(records) >= limit:
            break
        native = re.search(r'value="(\d+)"', block)
        title_match = re.search(r'job_tit"[^>]*>\s*<a[^>]*title="([^"]+)"', block)
        company_match = re.search(
            r'(?:corp_name|area_corp)"[^>]*>.*?<a[^>]*>\s*(.*?)\s*</a>', block, re.S)
        if not native or not title_match:
            errors.append(f"block {index}: rec_idx and title are required")
            continue
        native_id = native.group(1)
        sid = f"saramin:{native_id}"
        if sid in seen:
            continue
        seen.add(sid)
        title = clean_text(title_match.group(1))
        if not title:
            errors.append(f"block {index}: empty title")
            continue
        company = clean_text(company_match.group(1)) if company_match else ""
        company = company or None
        url = f"https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx={native_id}"
        evidence_raw = {"rec_idx": native_id, "title": title, "company": company, "query": query}
        records.append({
            "schema_version": SCHEMA_VERSION, "record_type": "job_posting",
            "source": source, "source_id": sid,
            "company": company, "company_candidate": company,
            "company_confidence": "public_listing" if company else "unknown",
            "title": title, "url": url, "published_at": None,
            "stack": None, "location": None,
            "review_required": company is None,
            "evidence": evidence(source, sid, url, retrieved_at, evidence_raw),
        })
    status = "ok" if records else "invalid_response"
    return SourceResult(status, source, records, errors, {
        "query": query, "recognized_blocks": len(blocks), "bounded_pages": 1,
        "bounded_limit": limit,
    })


def collect_saramin(query: str, limit: int, fixture: str | None, retrieved_at: str) -> SourceResult:
    source = "saramin-public-search"
    if fixture:
        try:
            raw = Path(fixture).read_bytes()
            if len(raw) > MAX_RESPONSE_BYTES:
                return SourceResult("invalid_response", source, errors=[
                    f"fixture exceeded {MAX_RESPONSE_BYTES} bytes"
                ], metadata={"query": query})
            status, error = "ok", None
        except OSError as exc:
            status, raw, error = "failed", None, f"fixture read failed: {exc}"
    else:
        encoded = urllib.parse.urlencode({"searchword": query, "recruitPage": 1})
        status, raw, error = fetch_bytes(f"{SARAMIN_ENDPOINT}?{encoded}", source)
    if status != "ok" or raw is None:
        return SourceResult(status, source, errors=[error or "Saramin source failed"],
                            metadata={"query": query, "bounded_pages": 1})
    return normalize_saramin_html(raw, query, retrieved_at, limit)


def combine_job_search(results: list[SourceResult]) -> SourceResult:
    """Combine explicit providers without hiding a partial source failure."""
    if not results:
        raise ValueError("at least one source result is required")
    metadata = {"sources": [{"source": item.source, "status": item.status,
                              "record_count": len(item.records)} for item in results]}
    errors = [message for item in results for message in item.errors]
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in results:
        for record in item.records:
            key = (str(record.get("source")), str(record.get("source_id")))
            if key not in seen:
                seen.add(key); records.append(record)
    failures = [item.status for item in results if item.status not in ("ok", "empty")]
    if failures:
        status = "blocked" if "blocked" in failures else (
            "invalid_response" if "invalid_response" in failures else "failed")
        metadata["partial_records_not_committed"] = len(records)
        return SourceResult(status, "wanted+saramin-public-search", records, errors, metadata)
    return SourceResult("ok" if records else "empty", "wanted+saramin-public-search",
                        records, errors, metadata)


TYPED_ALIASES = {
    "company": ("company", "company_name", "organization", "issuer", "buyer", "partner", "기관명", "수요기관", "회사명"),
    "title": ("title", "name", "notice_title", "project", "공고명", "사업명"),
    "url": ("url", "link", "notice_url", "공고url", "링크"),
    "published_at": ("published_at", "date", "posted_at", "notice_date", "게시일", "공고일"),
    "source": ("source", "portal", "registry", "출처"),
    "source_id": ("source_id", "id", "notice_id", "공고번호"),
    "location": ("location", "region", "country", "지역", "국가"),
    "description": ("description", "summary", "details", "내용", "요약"),
}


def _typed_lookup(row: dict[str, Any], field_name: str) -> Any:
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for alias in TYPED_ALIASES[field_name]:
        if alias.lower() in lowered:
            return lowered[alias.lower()]
    return None


def normalize_typed_rows(rows: Iterable[Any], record_type: str, retrieved_at: str,
                         source_default: str = "user-file") -> SourceResult:
    """Normalize user-provided funding, tender, or partner evidence.

    This adapter performs no scraping and never upgrades a candidate identity to
    verified. A clean empty file remains ``empty``; malformed-only input is
    ``invalid_response``.
    """
    if record_type not in {"funding_signal", "procurement", "overseas_partner"}:
        raise ValueError("unsupported typed record_type")
    rows = list(rows)
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            errors.append(f"row {index}: expected object")
            continue
        title = clean_text(_typed_lookup(raw, "title"))
        url = canonical_url(_typed_lookup(raw, "url"))
        if not title or not url:
            errors.append(f"row {index}: title and public http(s) URL are required")
            continue
        company = clean_text(_typed_lookup(raw, "company")) or None
        source = clean_text(_typed_lookup(raw, "source")) or source_default
        sid = source_id_from_url(source, url, _typed_lookup(raw, "source_id"))
        key = f"{source.casefold()}:{sid}"
        if key in seen:
            continue
        seen.add(key)
        description = clean_text(_typed_lookup(raw, "description")) or None
        records.append({
            "schema_version": SCHEMA_VERSION, "record_type": record_type,
            "source": source, "source_id": sid, "company": company,
            "company_candidate": company, "company_confidence": "provided" if company else "unknown",
            "title": title, "description": description, "url": url,
            "published_at": normalize_date(_typed_lookup(raw, "published_at")),
            "stack": None, "location": clean_text(_typed_lookup(raw, "location")) or None,
            "review_required": company is None,
            "evidence": evidence(source, sid, url, retrieved_at, raw),
        })
    status = "ok" if records else ("invalid_response" if errors else "empty")
    return SourceResult(status, f"{record_type}-import", records, errors, {
        "duplicates_removed": max(0, len(rows) - len(records) - len(errors)),
    })


def import_typed(path: str, format_name: str, record_type: str, retrieved_at: str) -> SourceResult:
    status, rows, error = read_job_rows(path, format_name)
    if status != "ok":
        return SourceResult(status, f"{record_type}-import", errors=[error or "typed import failed"])
    return normalize_typed_rows(rows or [], record_type, retrieved_at)


ATS_URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
    "lever": "https://api.lever.co/v0/postings/{token}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{token}",
}


def normalize_ats(payload: Any, provider: str, token: str, company: str, retrieved_at: str, limit: int) -> SourceResult:
    source = f"ats:{provider}:{token}"
    if provider in ("greenhouse", "ashby"):
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            return SourceResult("invalid_response", source, errors=[f"{provider}: expected object with jobs list"])
        jobs = payload["jobs"]
    elif provider == "lever":
        if not isinstance(payload, list):
            return SourceResult("invalid_response", source, errors=["lever: expected a JSON list"])
        jobs = payload
    else:
        return SourceResult("invalid_response", source, errors=["unsupported ATS provider"])
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, job in enumerate(jobs[:limit]):
        if not isinstance(job, dict):
            errors.append(f"row {index}: expected object")
            continue
        if provider == "greenhouse":
            title = clean_text(job.get("title"))
            location = clean_text((job.get("location") or {}).get("name") if isinstance(job.get("location"), dict) else None)
            url = canonical_url(job.get("absolute_url"))
            native_id = job.get("id")
            published = job.get("updated_at")
        elif provider == "lever":
            title = clean_text(job.get("text"))
            location = clean_text((job.get("categories") or {}).get("location") if isinstance(job.get("categories"), dict) else None)
            url = canonical_url(job.get("hostedUrl"))
            native_id = job.get("id")
            published = job.get("createdAt")
        else:
            title = clean_text(job.get("title"))
            location = clean_text(job.get("location"))
            url = canonical_url(job.get("jobUrl") or job.get("applyUrl"))
            native_id = job.get("id")
            published = job.get("publishedAt")
        if not title or not url:
            errors.append(f"row {index}: title and public URL are required")
            continue
        sid = f"{provider}:{native_id}" if native_id is not None and str(native_id).strip() else source_id_from_url(source, url)
        rows.append({
            "schema_version": SCHEMA_VERSION,
            "record_type": "job_posting",
            "source": source,
            "source_id": sid,
            "company": company,
            "company_candidate": company,
            "company_confidence": "provided",
            "title": title,
            "url": url,
            "published_at": normalize_date(published),
            "stack": None,
            "location": location or None,
            "review_required": False,
            "evidence": evidence(source, sid, url, retrieved_at, job),
        })
    status = "ok" if rows else ("invalid_response" if errors else "empty")
    return SourceResult(status, source, rows, errors)


def collect_ats(provider: str, token: str, company: str, limit: int, fixture: str | None, retrieved_at: str) -> SourceResult:
    source = f"ats:{provider}:{token}"
    if fixture:
        status, payload, error = load_fixture(fixture)
    else:
        safe_token = urllib.parse.quote(token, safe="")
        status, payload, error = fetch_json(ATS_URLS[provider].format(token=safe_token), source)
    if status != "ok":
        return SourceResult(status, source, errors=[error or "ATS source failed"])
    return normalize_ats(payload, provider, token, company, retrieved_at, limit)


def load_source_config(path: str) -> tuple[dict[str, Any] | None, str | None]:
    """Read only the non-secret setup fields used by source filtering."""
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        return None, f"config read failed: {exc}"
    if len(raw) > 1024 * 1024:
        return None, "config exceeded 1048576 bytes"
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "config must be valid UTF-8 JSON"
    if not isinstance(data, dict):
        return None, "config must be a JSON object"
    for key in ("job_keywords", "funding_keywords", "keywords", "region", "exclude_keywords"):
        if key in data and not isinstance(data[key], str):
            return None, f"config field {key} must be a string"
    if "workflows" in data:
        workflows = data["workflows"]
        if not isinstance(workflows, list) or any(not isinstance(value, str) for value in workflows):
            return None, "config field workflows must be a string list"
        allowed = {"jobs", "funding", "tenders", "overseas"}
        if len(workflows) != len(set(workflows)) or any(value not in allowed for value in workflows):
            return None, "config field workflows contains an unknown or duplicate value"
    return data, None


def split_filter_terms(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    terms = [clean_text(term).casefold() for term in re.split(r"[,;|/\n]+", value)]
    return list(dict.fromkeys(term for term in terms if term))


def workflow_enabled(config: dict[str, Any], workflow: str) -> bool:
    """A missing workflows field is backward compatible; an explicit list is authoritative."""
    return "workflows" not in config or workflow in config["workflows"]


def disabled_workflow_result(source: str, workflow: str) -> SourceResult:
    return SourceResult("empty", source, metadata={
        "filters": {
            "configured": True,
            "workflow": workflow,
            "workflow_enabled": False,
            "input_records": 0,
            "kept_records": 0,
            "excluded_by_include_keyword": 0,
            "excluded_by_exclude_keyword": 0,
            "excluded_by_region": 0,
            "region_unknown_kept": 0,
        }
    })


def apply_config_filters(result: SourceResult, config: dict[str, Any], workflow: str) -> SourceResult:
    """Filter successful records without changing evidence or masking source failures."""
    if result.status not in ("ok", "empty"):
        return result
    specific_key = {"jobs": "job_keywords", "funding": "funding_keywords"}.get(workflow)
    include_terms = split_filter_terms(config.get(specific_key)) if specific_key else []
    if not include_terms:
        include_terms = split_filter_terms(config.get("keywords"))
    exclude_terms = split_filter_terms(config.get("exclude_keywords"))
    region_terms = split_filter_terms(config.get("region")) if workflow == "jobs" else []
    counts = {
        "configured": True,
        "workflow": workflow,
        "workflow_enabled": True,
        "input_records": len(result.records),
        "kept_records": 0,
        "include_keyword_count": len(include_terms),
        "exclude_keyword_count": len(exclude_terms),
        "region_term_count": len(region_terms),
        "excluded_by_include_keyword": 0,
        "excluded_by_exclude_keyword": 0,
        "excluded_by_region": 0,
        "region_unknown_kept": 0,
    }
    kept: list[dict[str, Any]] = []
    for record in result.records:
        stack = record.get("stack")
        stack_text = " ".join(str(value) for value in stack) if isinstance(stack, list) else ""
        searchable = " ".join(clean_text(record.get(key)) for key in (
            "title", "description", "company", "company_candidate", "sector_candidate", "round_candidate"
        ))
        searchable = f"{searchable} {stack_text} {clean_text(record.get('location'))}".casefold()
        if exclude_terms and any(term in searchable for term in exclude_terms):
            counts["excluded_by_exclude_keyword"] += 1
            continue
        if include_terms and not any(term in searchable for term in include_terms):
            counts["excluded_by_include_keyword"] += 1
            continue
        if region_terms:
            location = clean_text(record.get("location")).casefold()
            if not location:
                # Absence of location is unknown, not evidence of a mismatch.
                counts["region_unknown_kept"] += 1
            elif not any(term in location or location in term for term in region_terms):
                counts["excluded_by_region"] += 1
                continue
        kept.append(record)
    counts["kept_records"] = len(kept)
    metadata = dict(result.metadata)
    metadata["filters"] = counts
    return SourceResult("ok" if kept else "empty", result.source, kept, list(result.errors), metadata)


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Read-only outbound funding and job source adapters")
    sub = ap.add_subparsers(dest="command", required=True)
    funding = sub.add_parser("funding", help="collect bounded public WordPress funding candidates")
    funding.add_argument("--pages", type=int, default=1)
    funding.add_argument("--per-page", type=int, default=10)
    funding.add_argument("--fixture")
    funding.add_argument("--as-of")
    funding.add_argument("--config", help="setup.json; applies workflow, keyword, exclusion filters")

    jobs = sub.add_parser("jobs-import", help="normalize a user-provided CSV or JSON job export")
    jobs.add_argument("path")
    jobs.add_argument("--format", choices=("auto", "csv", "json"), default="auto")
    jobs.add_argument("--as-of")
    jobs.add_argument("--config", help="setup.json; applies workflow, keyword, region, exclusion filters")

    ats = sub.add_parser("ats", help="read one public Greenhouse, Lever, or Ashby board")
    ats.add_argument("--provider", choices=tuple(ATS_URLS), required=True)
    ats.add_argument("--token", required=True, help="public board slug, not a credential")
    ats.add_argument("--company", required=True)
    ats.add_argument("--limit", type=int, default=50)
    ats.add_argument("--fixture")
    ats.add_argument("--as-of")
    ats.add_argument("--config", help="setup.json; applies workflow, keyword, region, exclusion filters")
    wanted = sub.add_parser("wanted", help="read one bounded public Wanted keyword search")
    wanted.add_argument("query")
    wanted.add_argument("--limit", type=int, default=20)
    wanted.add_argument("--fixture", help="synthetic Wanted JSON fixture")
    wanted.add_argument("--as-of")
    wanted.add_argument("--config", help="setup.json; applies job keyword, region, exclusion filters")
    saramin = sub.add_parser("saramin", help="read one bounded public Saramin keyword search page")
    saramin.add_argument("query")
    saramin.add_argument("--limit", type=int, default=20)
    saramin.add_argument("--fixture", help="synthetic Saramin HTML fixture")
    saramin.add_argument("--as-of")
    saramin.add_argument("--config", help="setup.json; applies job keyword, region, exclusion filters")
    typed = sub.add_parser("typed-import", help="normalize a funding, tender, or overseas partner CSV/JSON export")
    typed.add_argument("path")
    typed.add_argument("--type", choices=("funding_signal", "procurement", "overseas_partner"), required=True)
    typed.add_argument("--format", choices=("auto", "csv", "json"), default="auto")
    typed.add_argument("--as-of")
    typed.add_argument("--config", help="setup.json; applies workflow and conservative keyword filters")
    return ap


def exit_code(status: str) -> int:
    return {"ok": 0, "empty": 0, "blocked": 2, "failed": 3, "invalid_response": 4}[status]


def main(argv: list[str] | None = None) -> int:
    ap = parser()
    args = ap.parse_args(argv)
    retrieved_at = args.as_of or utc_now()
    if normalize_date(retrieved_at) is None:
        ap.error("--as-of must be an ISO-8601 date or datetime")
    config: dict[str, Any] | None = None
    if args.config:
        config, config_error = load_source_config(args.config)
        if config_error:
            source = ("platum-wordpress" if args.command == "funding" else
                      f"ats:{args.provider}:{args.token}" if args.command == "ats" else "job-import")
            result = SourceResult("invalid_response", source, errors=[config_error])
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
            return exit_code(result.status)
    workflow = ("funding" if args.command == "funding" else
                {"funding_signal": "funding", "procurement": "tenders",
                 "overseas_partner": "overseas"}.get(args.type) if args.command == "typed-import" else "jobs")
    if config is not None and not workflow_enabled(config, workflow):
        source = ("platum-wordpress" if workflow == "funding" else
                  f"ats:{args.provider}:{args.token}" if args.command == "ats" else "job-import")
        result = disabled_workflow_result(source, workflow)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return exit_code(result.status)
    if args.command == "funding":
        if not 1 <= args.pages <= 3 or not 1 <= args.per_page <= 20:
            ap.error("funding bounds: --pages 1..3, --per-page 1..20")
        result = collect_funding(args.pages, args.per_page, args.fixture, retrieved_at)
    elif args.command == "jobs-import":
        result = import_jobs(args.path, args.format, retrieved_at)
    elif args.command == "ats":
        if not 1 <= args.limit <= 100:
            ap.error("ATS bound: --limit 1..100")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", args.token):
            ap.error("ATS token must be a public board slug (letters, digits, dot, underscore, hyphen)")
        if not args.company.strip():
            ap.error("ATS --company must not be empty")
        result = collect_ats(args.provider, args.token, args.company.strip(), args.limit, args.fixture, retrieved_at)
    elif args.command in ("wanted", "saramin"):
        if not 1 <= args.limit <= 50:
            ap.error(f"{args.command} bound: --limit 1..50")
        if any(ord(char) < 32 for char in args.query):
            ap.error(f"{args.command} query must be 1..200 printable characters")
        query = clean_text(args.query)
        if not query or len(query) > 200:
            ap.error(f"{args.command} query must be 1..200 printable characters")
        result = (collect_wanted(query, args.limit, args.fixture, retrieved_at)
                  if args.command == "wanted" else
                  collect_saramin(query, args.limit, args.fixture, retrieved_at))
    else:
        result = import_typed(args.path, args.format, args.type, retrieved_at)
    if config is not None:
        result = apply_config_filters(result, config, workflow)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return exit_code(result.status)


if __name__ == "__main__":
    raise SystemExit(main())
