"""Public-source discovery and evidence-backed claim extraction."""

from __future__ import annotations

from html.parser import HTMLParser
import json
import re
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
import urllib.request

from tech_connector.services.open_knowledge_policy_service import (
    assess_open_knowledge_source,
)
from tech_connector.services.public_https_service import create_public_https_context


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]{2,}")
_SPACE_RE = re.compile(r"\s+")


def sanitize_public_research_query(value: str) -> str:
    """Remove project identities and local paths before an automatic web query."""

    text = str(value or "")
    text = re.sub(r"(?i)/Game/[A-Za-z0-9_./-]+", " ", text)
    text = re.sub(r"(?i)\b[A-Z]:\\[^\s]+", " ", text)
    text = re.sub(r"(?i)https?://\S+|\b\S+@\S+\.\S+\b", " ", text)
    text = re.sub(r"(?i)\b(?:BP|ABP|SKM|SK|AM|IA|IMC)_[A-Za-z0-9_]+\b", " ", text)
    text = re.sub(r"[^A-Za-z0-9_+ .-]+", " ", text)
    return _SPACE_RE.sub(" ", text).strip()[:240]


class _ReadableHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._title_depth = 0
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript", "svg", "nav", "footer"}:
            self._ignored_depth += 1
        if lowered == "title":
            self._title_depth += 1

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript", "svg", "nav", "footer"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
        if lowered == "title":
            self._title_depth = max(0, self._title_depth - 1)

    def handle_data(self, data: str) -> None:
        value = _SPACE_RE.sub(" ", str(data or "")).strip()
        if not value:
            return
        if self._title_depth:
            self.title_parts.append(value)
        if not self._ignored_depth:
            self.text_parts.append(value)


class _SearchResultHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._active_href = ""
        self._active_title: list[str] = []
        self.results: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        classes = set(values.get("class", "").split())
        if "result-link" in classes:
            self._active_href = values.get("href", "")
            self._active_title = []

    def handle_data(self, data: str) -> None:
        if self._active_href:
            self._active_title.append(str(data or ""))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._active_href:
            self.results.append(
                (
                    self._active_href,
                    _SPACE_RE.sub(" ", " ".join(self._active_title)).strip(),
                )
            )
            self._active_href = ""
            self._active_title = []


def _search_result_url(value: str) -> str:
    href = str(value or "").strip()
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.netloc.lower().endswith("duckduckgo.com"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return unquote(target)
    return href


def _default_opener():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=create_public_https_context()),
    )


def _source_kind(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host == "dev.epicgames.com" or host.endswith(".epicgames.com"):
        return "official_docs"
    if host == "github.com" or host.endswith(".github.com"):
        return "primary_repository"
    return "public_guide"


def _source_policy_fields(url: str, kind: str) -> dict[str, Any]:
    official = kind == "official_docs"
    return {
        "url": url,
        "source_kind": kind,
        "public_access": True,
        "access": "public",
        "auth_required": False,
        "paid": False,
        "private": False,
        "official_public_documentation": official,
        "license": "Official public documentation" if official else "Unverified public source terms",
        "allow_task_use": True,
    }


def search_public_sources(
    query: str,
    *,
    engine_version: str = "",
    limit: int = 8,
    official_only: bool = False,
    allowed_domains: Iterable[str] | None = None,
    timeout: float = 10.0,
    opener=None,
) -> dict[str, Any]:
    """Search public HTTPS sources and return candidates, never adopted claims."""

    query_text = str(query or "").strip()
    if not query_text:
        raise ValueError("query cannot be empty")
    domains = [str(value).strip().lower() for value in allowed_domains or [] if str(value).strip()]
    if official_only and "dev.epicgames.com" not in domains:
        domains.insert(0, "dev.epicgames.com")
    search_text = " ".join(
        value for value in (query_text, f"Unreal Engine {engine_version}" if engine_version else "") if value
    )
    if domains:
        search_text += " " + " OR ".join(f"site:{domain}" for domain in domains)
    elif official_only:
        search_text += " site:dev.epicgames.com"

    endpoint = "https://lite.duckduckgo.com/lite/?q=" + quote_plus(search_text)
    request = urllib.request.Request(
        endpoint,
        headers={"User-Agent": "AI-Studio-Knowledge-Research/1.0"},
    )
    client = opener or _default_opener()
    errors: list[str] = []
    candidates: list[dict[str, Any]] = []
    try:
        with client.open(request, timeout=float(timeout)) as response:
            payload = response.read(1024 * 1024).decode("utf-8", errors="replace")
        parser = _SearchResultHTML()
        parser.feed(payload)
        seen: set[str] = set()
        for raw_url, result_title in parser.results:
            url = _search_result_url(raw_url)
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.netloc:
                continue
            host = parsed.netloc.lower()
            if domains and not any(host == domain or host.endswith("." + domain) for domain in domains):
                continue
            if url in seen:
                continue
            seen.add(url)
            kind = _source_kind(url)
            source = {
                **_source_policy_fields(url, kind),
                "title": result_title,
                "search_snippet": "",
                "query": query_text,
                "engine_version": str(engine_version or ""),
                "candidate_status": "unverified_source_candidate",
            }
            source["knowledge_policy"] = assess_open_knowledge_source(source)
            candidates.append(source)
            if len(candidates) >= max(1, int(limit)):
                break
    except Exception as exc:
        errors.append(str(exc))

    return {
        "framework": "public_knowledge_source_search_v1",
        "ok": bool(candidates),
        "query": query_text,
        "search_endpoint": endpoint,
        "candidates": candidates,
        "errors": errors,
        "claims_adopted": False,
        "mutation_allowed": False,
    }


def _fetch_public_document(source: dict[str, Any], *, opener, timeout: float) -> dict[str, Any]:
    url = str(source.get("url") or "").strip()
    if urlparse(url).scheme != "https":
        raise ValueError("Only HTTPS knowledge sources may be fetched")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "AI-Studio-Knowledge-Research/1.0"},
    )
    with opener.open(request, timeout=float(timeout)) as response:
        content_type = str(response.headers.get("Content-Type") or "")
        payload = response.read(2 * 1024 * 1024)
    text = payload.decode("utf-8", errors="replace")
    title = str(source.get("title") or "")
    if "html" in content_type.lower() or "<html" in text[:500].lower():
        parser = _ReadableHTML()
        parser.feed(text)
        text = "\n".join(parser.text_parts)
        title = " ".join(parser.title_parts).strip() or title
    text = _SPACE_RE.sub(" ", text).strip()
    return {"url": url, "title": title, "text": text, "content_type": content_type}


def _evidence_windows(text: str, query: str, limit: int = 12) -> list[str]:
    terms = {
        value.lower()
        for value in _WORD_RE.findall(query or "")
        if value.lower() not in {"unreal", "engine", "build", "system", "feature", "with"}
    }
    sentences = [
        _SPACE_RE.sub(" ", value).strip()
        for value in re.split(r"(?<=[.!?])\s+|\s*[\r\n]+\s*", text or "")
        if 30 <= len(value.strip()) <= 800
    ]
    ranked = sorted(
        enumerate(sentences),
        key=lambda row: (
            sum(1 for term in terms if term in row[1].lower()),
            -row[0],
        ),
        reverse=True,
    )
    return [sentence for _index, sentence in ranked[:limit] if sentence]


def _claim_terms(value: str) -> set[str]:
    stop = {
        "about", "after", "also", "and", "are", "before", "from", "into", "only",
        "that", "the", "their", "this", "through", "with", "without", "your",
    }
    return {
        token.lower()
        for token in _WORD_RE.findall(value or "")
        if token.lower() not in stop
    }


def verify_known_public_claims(
    sources: Iterable[dict[str, Any]],
    *,
    max_sources: int = 6,
    timeout: float = 10.0,
    opener=None,
) -> dict[str, Any]:
    """Refresh known source pointers without asking a model to restate the claim."""

    client = opener or _default_opener()
    verified: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    errors: list[str] = []
    for raw_source in list(sources or [])[: max(1, int(max_sources))]:
        source = dict(raw_source or {})
        claim = _SPACE_RE.sub(" ", str(source.get("claim") or "")).strip()
        if not claim:
            continue
        try:
            document = _fetch_public_document(source, opener=client, timeout=timeout)
            windows = _evidence_windows(document["text"], claim, limit=8)
            claim_terms = _claim_terms(claim)
            ranked = []
            for sentence in windows:
                sentence_terms = _claim_terms(sentence)
                hits = claim_terms.intersection(sentence_terms)
                coverage = len(hits) / max(1, len(claim_terms))
                ranked.append((coverage, len(hits), sentence))
            coverage, hits, sentence = max(ranked, default=(0.0, 0, ""))
            if hits < 3 or coverage < 0.2:
                rejected.append(
                    {
                        "source": source,
                        "claim": claim,
                        "reason": "Fetched source text did not provide enough lexical support.",
                        "coverage": coverage,
                        "supporting_term_count": hits,
                    }
                )
                continue
            quote, bounded = _bounded_exact_quote(sentence, claim)
            verified.append(
                {
                    "claim": claim,
                    "supporting_quote": quote,
                    "applies_to_version": str(source.get("applies_to_version") or source.get("engine_version") or ""),
                    "prerequisites": [str(value) for value in source.get("prerequisites") or []],
                    "source": {
                        **source,
                        "url": document["url"],
                        "title": document["title"],
                    },
                    "support_coverage": round(coverage, 3),
                    "evidence_origin": "live_refresh_of_known_public_source",
                    "status": "source_supported",
                    "quote_bounded_by_validator": bounded,
                }
            )
        except Exception as exc:
            errors.append(f"{source.get('url')}: {exc}")
    return {
        "ok": bool(verified),
        "claims": verified,
        "rejected": rejected,
        "errors": errors,
    }


def _parse_model_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _bounded_exact_quote(quote: str, claim: str, max_words: int = 25) -> tuple[str, bool]:
    words = str(quote or "").split()
    if len(words) <= max_words:
        return " ".join(words), False
    claim_terms = {value.lower() for value in _WORD_RE.findall(claim or "")}
    best = " ".join(words[:max_words])
    best_score = -1
    for index in range(0, len(words) - max_words + 1):
        candidate_words = words[index : index + max_words]
        candidate_terms = {re.sub(r"[^A-Za-z0-9_+-]", "", value).lower() for value in candidate_words}
        score = len(claim_terms.intersection(candidate_terms))
        if score > best_score:
            best = " ".join(candidate_words)
            best_score = score
    return best, True


def _default_claim_extractor(payload: dict[str, Any]) -> dict[str, Any]:
    from tech_connector.knowledge.search import query_ollama_text

    schema = {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim": {"type": "string"},
                        "supporting_quote": {"type": "string"},
                        "applies_to_version": {"type": "string"},
                        "prerequisites": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["claim", "supporting_quote", "applies_to_version", "prerequisites"],
                },
            }
        },
        "required": ["claims"],
    }
    response = query_ollama_text(
        "qwen2.5-coder:3b",
        (
            "Extract only implementation facts explicitly supported by the supplied source evidence. "
            "Each supporting_quote must be an exact quote of at most 25 words from the evidence. "
            "Do not use outside knowledge and do not infer missing details. Return JSON only."
        ),
        json.dumps(payload, indent=2),
        num_ctx=8192,
        num_predict=1200,
        timeout=75,
        prefer_coder=True,
        coder_preference="small",
        response_format=schema,
        temperature=0.0,
    )
    return _parse_model_json(response)


def extract_public_source_claims(
    sources: Iterable[dict[str, Any]],
    *,
    query: str = "",
    engine_version: str = "",
    max_sources: int = 6,
    timeout: float = 10.0,
    opener=None,
    claim_extractor: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fetch public sources and retain only claims with exact source support."""

    client = opener or _default_opener()
    extractor = claim_extractor or _default_claim_extractor
    claims: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    errors: list[str] = []
    for raw_source in list(sources or [])[: max(1, int(max_sources))]:
        source = dict(raw_source or {})
        source.setdefault("allow_task_use", True)
        source.setdefault("public_access", True)
        source.setdefault("access", "public")
        policy = assess_open_knowledge_source(source)
        if not policy.get("task_use_allowed"):
            rejected.append({"source": source, "reason": policy.get("reasons") or []})
            continue
        try:
            document = _fetch_public_document(source, opener=client, timeout=timeout)
            windows = _evidence_windows(document["text"], " ".join((query, document["title"])))
            if not windows:
                rejected.append({"source": source, "reason": ["No relevant readable evidence was found."]})
                continue
            extracted = extractor(
                {
                    "query": query,
                    "engine_version": engine_version,
                    "source": {"url": document["url"], "title": document["title"]},
                    "evidence": windows,
                }
            )
            normalized_text = _SPACE_RE.sub(" ", document["text"]).lower()
            for row in list(extracted.get("claims") or []):
                candidate = dict(row or {})
                quote = _SPACE_RE.sub(" ", str(candidate.get("supporting_quote") or "")).strip()
                claim = _SPACE_RE.sub(" ", str(candidate.get("claim") or "")).strip()
                if not claim or not quote:
                    rejected.append({"source": source, "claim": candidate, "reason": ["Claim or bounded quote is invalid."]})
                    continue
                if quote.lower() not in normalized_text:
                    rejected.append({"source": source, "claim": candidate, "reason": ["Supporting quote was not found in fetched source text."]})
                    continue
                quote, quote_repaired = _bounded_exact_quote(quote, claim)
                if quote.lower() not in normalized_text:
                    rejected.append({"source": source, "claim": candidate, "reason": ["Bounded supporting quote was not found in fetched source text."]})
                    continue
                claims.append(
                    {
                        "claim": claim,
                        "supporting_quote": quote,
                        "applies_to_version": str(candidate.get("applies_to_version") or engine_version or ""),
                        "prerequisites": [str(value) for value in candidate.get("prerequisites") or []],
                        "source": {
                            **source,
                            "url": document["url"],
                            "title": document["title"],
                            "knowledge_policy": policy,
                        },
                        "evidence_origin": "fetched_public_source",
                        "status": "source_supported",
                        "quote_bounded_by_validator": quote_repaired,
                    }
                )
        except Exception as exc:
            errors.append(f"{source.get('url')}: {exc}")

    return {
        "framework": "public_knowledge_claim_extraction_v1",
        "ok": bool(claims),
        "query": query,
        "engine_version": engine_version,
        "claims": claims,
        "rejected": rejected,
        "errors": errors,
        "mutation_allowed": False,
        "knowledge_promotion_allowed": False,
        "promotion_rule": "Claims may enter reusable knowledge only after project-fit and runtime proof pass.",
    }


def run_automatic_feature_research(
    plan: dict[str, Any],
    *,
    settings: dict[str, Any] | None = None,
    searcher: Callable[..., dict[str, Any]] | None = None,
    extractor: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve a missing-technique branch before asking the user to choose."""

    settings = dict(settings or {})
    plan = dict(plan or {})
    searcher = searcher or search_public_sources
    extractor = extractor or extract_public_source_claims
    official_enabled = bool(settings.get("auto_research_official_docs", True))
    web_enabled = bool(
        settings.get("enable_live_sources")
        and settings.get("research_web_techniques")
    )
    if not official_enabled and not web_enabled:
        return {
            "framework": "automatic_feature_research_v1",
            "ok": False,
            "status": "disabled",
            "reason": "Automatic official and public-web research are disabled.",
            "mutation_allowed": False,
        }

    sources: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    techniques = list(
        dict(plan.get("expert_technique_selection") or {}).get("techniques") or []
    )
    for technique in techniques:
        for raw_source in dict(technique or {}).get("sources") or []:
            source = dict(raw_source or {})
            url = str(source.get("url") or "").strip()
            if urlparse(url).scheme != "https" or not url or url in seen:
                continue
            kind = str(source.get("source_kind") or source.get("kind") or _source_kind(url))
            source = {
                **_source_policy_fields(url, kind),
                **source,
                "url": url,
                "source_kind": kind,
                "title": str(source.get("title") or technique.get("title") or ""),
                "candidate_status": "known_pointer_pending_live_refresh",
            }
            source["knowledge_policy"] = assess_open_knowledge_source(source)
            if source["knowledge_policy"].get("task_use_allowed"):
                seen.add(url)
                sources.append(source)

    technique_terms = []
    for technique in techniques:
        title = sanitize_public_research_query(str(dict(technique or {}).get("title") or ""))
        operations = " ".join(
            str(value).replace(".", " ")
            for value in dict(technique or {}).get("operations") or []
        )
        query = sanitize_public_research_query(
            " ".join(("Unreal Engine 5.8", title, operations, "official documentation"))
        )
        if query and query not in technique_terms:
            technique_terms.append(query)
    sanitized_queries = technique_terms[:2] or [
        "Unreal Engine 5.8 gameplay feature architecture animation runtime validation official documentation"
    ]

    for query in sanitized_queries:
        if len(sources) >= 4:
            break
        result = searcher(
            query,
            engine_version="5.8",
            limit=4,
            official_only=not web_enabled,
            timeout=15.0,
        )
        errors.extend(str(value) for value in result.get("errors") or [])
        for source in result.get("candidates") or []:
            url = str(source.get("url") or "")
            if url and url not in seen:
                seen.add(url)
                sources.append(dict(source))
        if len(sources) >= 4:
            break

    if not sources:
        return {
            "framework": "automatic_feature_research_v1",
            "ok": False,
            "status": "no_public_sources_found",
            "queries": sanitized_queries,
            "sources": [],
            "claims": [],
            "errors": errors,
            "project_identifiers_sent": False,
            "mutation_allowed": False,
        }

    refreshed = verify_known_public_claims(sources, max_sources=6, timeout=15.0)
    claims = list(refreshed.get("claims") or [])
    extracted = {"claims": [], "rejected": [], "errors": []}
    if not claims:
        discovery_sources = [source for source in sources if not source.get("claim")][:1] or sources[:1]
        extracted = extractor(
            discovery_sources,
            query=" ".join(
                str(source.get("title") or "") for source in discovery_sources
            ),
            engine_version="5.8",
            max_sources=1,
            timeout=15.0,
        )
        claims.extend(list(extracted.get("claims") or []))
    return {
        "framework": "automatic_feature_research_v1",
        "ok": bool(claims),
        "status": "source_claims_ready" if claims else "source_claims_unresolved",
        "queries": sanitized_queries,
        "sources": sources,
        "claims": claims,
        "rejected_claims": [
            *list(refreshed.get("rejected") or []),
            *list(extracted.get("rejected") or []),
        ],
        "errors": [
            *errors,
            *[str(value) for value in refreshed.get("errors") or []],
            *[str(value) for value in extracted.get("errors") or []],
        ],
        "source_policy": "public_https_only",
        "project_identifiers_sent": False,
        "mutation_allowed": False,
        "knowledge_promotion_allowed": False,
    }
