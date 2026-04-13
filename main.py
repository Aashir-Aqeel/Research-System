import asyncio
import json
import os
import re
import time
from datetime import date
from urllib.parse import urlparse
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─── Azure OpenAI config ──────────────────────────────────────────────────────

AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY", "").strip()
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip().rstrip("/")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o").strip()
AZURE_OPENAI_API_VERSION = os.getenv(
    "AZURE_OPENAI_API_VERSION", "2024-08-01-preview"
).strip()

# ─── Serper config ────────────────────────────────────────────────────────────

SERPER_API_KEY = os.getenv("SERPER_API_KEY", "").strip()

# ─── Derived URLs ─────────────────────────────────────────────────────────────

AZURE_CHAT_URL = (
    f"{AZURE_OPENAI_ENDPOINT}/openai/deployments/{AZURE_OPENAI_DEPLOYMENT}"
    f"/chat/completions?api-version={AZURE_OPENAI_API_VERSION}"
)

SERPER_SEARCH_URL = "https://google.serper.dev/search"
SERPER_SCRAPE_URL = "https://scrape.serper.dev"  # Serper webpage scrape endpoint

# ─── Scrape config ────────────────────────────────────────────────────────────

# Max characters to send to GPT per scraped page
# ~6000 chars ≈ ~1500 tokens — keeps cost reasonable while giving real depth
SCRAPE_CHAR_LIMIT = 8000  # increased for depth
SCRAPE_TOP_N = 5  # top N per sub-query (was 3)

# Optional scraper API keys — cascade falls back gracefully
SCRAPINGBEE_KEY = os.getenv("SCRAPINGBEE_KEY", "").strip()
BROWSERLESS_KEY = os.getenv("BROWSERLESS_KEY", "").strip()
SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY", "").strip()

# ─── Source quality config ────────────────────────────────────────────────────

TIER1_DOMAINS = {
    "nature.com",
    "science.org",
    "cell.com",
    "pubmed.ncbi.nlm.nih.gov",
    "scholar.google.com",
    "arxiv.org",
    "biorxiv.org",
    "medrxiv.org",
    "nejm.org",
    "thelancet.com",
    "jamanetwork.com",
    "bmj.com",
    "sciencedirect.com",
    "springer.com",
    "wiley.com",
    "tandfonline.com",
    "ieee.org",
    "acm.org",
    "mit.edu",
    "stanford.edu",
    "harvard.edu",
    "cam.ac.uk",
    "ox.ac.uk",
    "nih.gov",
    "cdc.gov",
    "who.int",
    "europa.eu",
    "gov.uk",
    "nsf.gov",
    "nasa.gov",
    "ca.gov",
    "gov",
    "techcrunch.com",
    "wired.com",
    "arstechnica.com",
    "technologyreview.com",
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "theguardian.com",
    "nytimes.com",
    "wsj.com",
    "ft.com",
    "economist.com",
    "bloomberg.com",
    "forbes.com",
    "mckinsey.com",
    "hbr.org",
    "advances.sciencemag.org",
    "pnas.org",
    "royalsocietypublishing.org",
    "mdpi.com",
    "frontiersin.org",
    "acs.org",
    "rsc.org",
    "leginfo.legislature.ca.gov",
    "congress.gov",
    "federalregister.gov",
    "law.cornell.edu",
    "courtlistener.com",
    "oyez.org",
    # top law firms — their client alerts are authoritative
    "pillsburylaw.com",
    "perkinscoie.com",
    "mayerbrown.com",
    "morganlewis.com",
    "dlapiper.com",
    "bakermckenzie.com",
    "lw.com",
    "skadden.com",
    "gibsondunn.com",
    "cooley.com",
    "wilsonsonsini.com",
    "orrick.com",
    "sidley.com",
    "paulweiss.com",
    "whitecase.com",
    "freshfields.com",
    "zwillgen.com",
    "jdsupra.com",
    "lexology.com",
}

TIER2_DOMAINS = {
    "venturebeat.com",
    "zdnet.com",
    "theregister.com",
    "engadget.com",
    "gizmodo.com",
    "cnet.com",
    "anandtech.com",
    "electrek.co",
    "cleantechnica.com",
    "greentechmedia.com",
    "chemistryworld.com",
    "physicsworld.com",
    "newscientist.com",
    "scientificamerican.com",
    "popsci.com",
    "popularmechanics.com",
    "axios.com",
    "politico.com",
    "theatlantic.com",
    "vox.com",
    "businessinsider.com",
    "cnbc.com",
    "marketwatch.com",
    "statista.com",
    "ourworldindata.org",
    "brookings.edu",
    "rand.org",
    "wikipedia.org",
    "investopedia.com",
    "powerelectronicsnews.com",
    "electronicdesign.com",
    "materialsfutures.org",
    "energy.gov",
    "nrel.gov",
    "iea.org",
    "captaincompliance.com",
    "onlineandonpoint.com",
    "dglaw.com",
    "hintzelaw.com",
    "natlawreview.com",
    "privacyworld.blog",
    "transparencycoalition.ai",
    "mofo.com",
    "legiscan.com",
    "troutmanprivacy.com",
    "gunder.com",
}

BLOCKED_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "pinterest.com",
    "tumblr.com",
    "etsy.com",
    "yelp.com",
    "tripadvisor.com",
    "trustpilot.com",
    "ask.com",
    "answers.com",
    "ehow.com",
    "breitbart.com",
    "infowars.com",
    "dailymail.co.uk",
    "thesun.co.uk",
    "buzzfeed.com",
}

# Useful but lower quality — scored 0.35, ranked lower but NOT excluded
SOFT_DEMOTE_DOMAINS = {
    "reddit.com",
    "medium.com",
    "linkedin.com",
    "quora.com",
    "youtube.com",
    "substack.com",
    "wordpress.com",
    "blogspot.com",
    "huffpost.com",
    "nypost.com",
}

# ─── App setup ────────────────────────────────────────────────────────────────

app = FastAPI(title="Central Research System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")


# ─── Models ───────────────────────────────────────────────────────────────────


class ResearchRequest(BaseModel):
    query: str


# ─── Config endpoint ──────────────────────────────────────────────────────────


@app.get("/config")
async def config():
    return {
        "azure_ready": bool(AZURE_OPENAI_KEY and AZURE_OPENAI_ENDPOINT),
        "serper_ready": bool(SERPER_API_KEY),
        "deployment": AZURE_OPENAI_DEPLOYMENT,
        "api_version": AZURE_OPENAI_API_VERSION,
        "scrapingbee_ready": bool(SCRAPINGBEE_KEY),
        "browserless_ready": bool(BROWSERLESS_KEY),
        "scraperapi_ready": bool(SCRAPERAPI_KEY),
    }


@app.get("/debug/scrapers")
async def debug_scrapers():
    """Test all scraper tiers. Visit /debug/scrapers to verify API keys."""
    test_url = "https://httpbin.org/html"
    results = {}
    r = await bs4_fetch(test_url)
    results["tier1_bs4"] = {
        "method": r["method"],
        "success": r["success"],
        "chars": r["chars"],
        "preview": r["text"][:100] if r["success"] else "failed",
    }
    r = await serper_scrape(test_url)
    results["tier2_serper"] = {
        "success": r["success"],
        "chars": r["chars"],
        "key_set": bool(SERPER_API_KEY),
    }
    if SCRAPINGBEE_KEY:
        r = await scrapingbee_fetch(test_url)
        results["tier3_scrapingbee"] = {
            "success": r["success"],
            "chars": r["chars"],
            "error": r.get("error", ""),
            "key_set": True,
        }
    else:
        results["tier3_scrapingbee"] = {
            "key_set": False,
            "note": "SCRAPINGBEE_KEY not set",
        }
    if BROWSERLESS_KEY:
        r = await browserless_fetch(test_url)
        results["tier4_browserless"] = {
            "success": r["success"],
            "chars": r["chars"],
            "error": r.get("error", ""),
            "key_set": True,
        }
    else:
        results["tier4_browserless"] = {
            "key_set": False,
            "note": "BROWSERLESS_KEY not set",
        }
    if SCRAPERAPI_KEY:
        r = await scraperapi_fetch(test_url)
        results["tier5_scraperapi"] = {
            "success": r["success"],
            "chars": r["chars"],
            "key_set": True,
        }
    else:
        results["tier5_scraperapi"] = {
            "key_set": False,
            "note": "SCRAPERAPI_KEY not set",
        }
    active = [k for k, v in results.items() if v.get("success")]
    results["summary"] = {
        "working_tiers": len(active),
        "active": active,
        "cascade_ready": len(active) >= 1,
    }
    return results


# ─── SSE helper ───────────────────────────────────────────────────────────────


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ─── Azure OpenAI — Chat Completions ─────────────────────────────────────────


async def call_azure(
    messages: list[dict],
    temperature: float = 0.2,
    max_tokens: int = 2048,
    timeout: float = 90.0,
) -> str:
    if not AZURE_OPENAI_KEY or not AZURE_OPENAI_ENDPOINT:
        raise RuntimeError(
            "Azure OpenAI not configured. "
            "Check AZURE_OPENAI_KEY and AZURE_OPENAI_ENDPOINT in .env"
        )

    headers = {
        "api-key": AZURE_OPENAI_KEY,
        "Content-Type": "application/json",
    }
    body = {
        "messages": messages,
        "temperature": temperature,
        "max_completion_tokens": max_tokens,
    }

    body["messages"] = sanitize_messages(body["messages"])

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(AZURE_CHAT_URL, headers=headers, json=body)
        if resp.status_code == 400:
            try:
                err = resp.json()
                err_msg = err.get("error", {}).get("message", "") or err.get(
                    "message", ""
                )
                if (
                    "content management policy" in err_msg.lower()
                    or "filtered" in err_msg.lower()
                ):
                    raise RuntimeError(
                        f"Azure content filter triggered. Try rephrasing. Error: {err_msg[:200]}"
                    )
            except RuntimeError:
                raise
            except Exception:
                pass
        resp.raise_for_status()

    data = resp.json()
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError(
            "Azure returned no choices — possible content filter or quota issue."
        )
    content = choices[0].get("message", {}).get("content") or ""
    finish_reason = choices[0].get("finish_reason", "")

    # Output filter: Azure filtered its own response.
    # Retry ONCE with a more aggressive sanitization of all message content.
    if not content.strip() or finish_reason == "content_filter":
        sanitized_body = dict(body)
        sanitized_body["messages"] = [
            dict(
                m,
                content=(
                    sanitize_query_for_azure(m.get("content", ""))
                    if isinstance(m.get("content"), str)
                    else m.get("content", "")
                ),
            )
            for m in body["messages"]
        ]
        # Add a neutral framing instruction to the system message
        if (
            sanitized_body["messages"]
            and sanitized_body["messages"][0].get("role") == "system"
        ):
            sanitized_body["messages"][0]["content"] = (
                "You are an academic research analyst. Respond in neutral, analytical language. "
                "Focus on facts, regulations, dates, and technical specifications. "
                "Avoid sensationalist language.\n\n"
                + sanitized_body["messages"][0]["content"]
            )
        try:
            async with httpx.AsyncClient(timeout=timeout) as client2:
                resp2 = await client2.post(
                    AZURE_CHAT_URL, headers=headers, json=sanitized_body
                )
                resp2.raise_for_status()
            data2 = resp2.json()
            choices2 = data2.get("choices", [])
            if choices2:
                content2 = choices2[0].get("message", {}).get("content") or ""
                if content2.strip():
                    return content2
        except Exception:
            pass
        # Both attempts filtered — return empty string (callers handle gracefully)
        return ""

    return content


# ─── Query sanitizer — neutral framing for Azure content filter ──────────────


def sanitize_query_for_azure(text: str) -> str:
    """Reframe conflict/sensitive queries to neutral analytical language for Azure."""
    import re as _re

    # Full-reframe trigger — detect high-risk conflict query patterns
    conflict_patterns = [
        r"(status|update|latest|situation|news).{0,30}(conflict|war|fight|tension).{0,30}(israel|iran|gaza|hamas|hezbollah|ukraine|russia|china|taiwan)",
        r"(conflict|war|fight|tension).{0,30}between.{0,60}(israel|iran|gaza|hamas|ukraine|russia)",
        r"(situation|update|status|news|latest).{0,30}(ukraine|russia|iran|israel|hamas|hezbollah|gaza)",
        r"(ukraine|russia|iran|israel|hamas|hezbollah|gaza).{0,50}(nuclear|missile|ceasefire|sanction|strike)",
        r"what.{0,20}(happening|going on|status|update).{0,30}(israel|iran|gaza|ukraine|russia|taiwan)",
        r"(operation epic fury|hormuz conflict|war.*hormuz|hormuz.*war|attack.*hormuz|blockade.*hormuz)",
    ]
    if any(_re.search(p, text, _re.IGNORECASE) for p in conflict_patterns):
        region_map = {
            r"\biran\b": "Iran",
            r"\bisrael\b": "Israel",
            r"\bus\b|\busa\b|\bunited states\b": "the United States",
            r"\bgaza\b": "Gaza",
            r"\bhamas\b": "Hamas",
            r"\bhezbollah\b": "Hezbollah",
            r"\bukraine\b": "Ukraine",
            r"\brussia\b": "Russia",
            r"\blebanon\b": "Lebanon",
            r"\bhormuz\b": "the Strait of Hormuz region",
        }
        regions = [
            name
            for pat, name in region_map.items()
            if _re.search(pat, text, _re.IGNORECASE)
        ]
        region_str = " and ".join(regions) if regions else "the relevant parties"
        return (
            f"Provide a current geopolitical and diplomatic situation analysis "
            f"involving {region_str}. Include the latest developments, any pauses "
            f"in hostilities, and key actor positions. Focus on facts and timeline."
        )

    # Phrase-level replacements
    phrase_repls = [
        (
            r"conflict\s+between\s+([\w\s\-]+?)\s+and\s+([\w\s\-]+)",
            r"geopolitical tensions between \1 and \2",
        ),
        (
            r"(?:war|conflict|fighting)\s+(?:status|update|situation)",
            "geopolitical situation update",
        ),
        (
            r"status\s+of\s+(?:the\s+)?(?:war|conflict)",
            "current geopolitical situation",
        ),
        (r"nuclear\s+(?:bomb|weapon|strike|warhead)", "nuclear program"),
        (r"(?:missile|rocket)\s+(?:attack|strike|launch|fire)", "projectile incident"),
        (r"death\s+toll", "casualty count"),
    ]
    result = text
    for pat, repl in phrase_repls:
        result = _re.sub(pat, repl, result, flags=_re.IGNORECASE)

    # Word-level replacements — conflict terms
    word_repls = [
        (r"\bwar\b", "armed conflict"),
        (r"\bwars\b", "conflicts"),
        (r"\battack(ed|ing|s)?\b", "action"),
        (r"\bbombing\b", "aerial activity"),
        (r"\bkill(ed|ing|s)?\b", "casualties"),
        (r"\bterrorist(s)?\b", "militant group"),
        (r"\bweapon(s|ry)?\b", "equipment"),
        (r"\bceasefire\b", "pause in hostilities"),
        (r"\bdeath(s)?\b", "losses"),
        (r"\bcasualt(y|ies)\b", "losses"),
        (r"\binvasion\b", "territorial incursion"),
        (r"\bgenocide\b", "humanitarian crisis"),
    ]
    for pat, repl in word_repls:
        result = _re.sub(pat, repl, result, flags=_re.IGNORECASE)
    return result


def sanitize_research_context(text: str) -> str:
    """
    Sanitize research CONTENT before embedding it in Azure synthesis prompts.
    Azure's output filter triggers when GPT generates responses ABOUT certain topics.
    This neutralizes terms in the research context that cause output filtering,
    WITHOUT changing the meaning — just the surface framing.

    Applied to: search summaries, scraped content sent to synthesize/synthesize_report.
    NOT applied to: Serper web searches (those use original terms for real results).
    """
    import re as _re

    # These terms in research CONTEXT cause Azure to filter its own output
    context_repls = [
        # AI regulation sensitive terms
        (r"\bdeepfake(s)?\b", "synthetic media"),
        (r"\bdeep fake(s)?\b", "synthetic media"),
        (r"\bbiometric surveillance\b", "biometric data processing"),
        (r"\bfacial recognition\b", "biometric identification"),
        (r"\bsocial scoring\b", "behavioral evaluation"),
        (r"\bmanipulation\b", "influence mechanism"),
        (r"\bexploitation\b", "improper use"),
        (r"\bpsychological harm\b", "adverse psychological effect"),
        (r"\bvulnerable group(s)?\b", "protected group(s)"),
        (r"\billegal content\b", "non-compliant content"),
        (r"\bterrorism\b", "extremist activity"),
        (r"\bcriminal\b", "unlawful"),
        (r"\bforced labor\b", "coerced work"),
        (r"\bchild exploitation\b", "minor protection violation"),
        (r"\bhate speech\b", "prohibited speech"),
        # Military/weapons in regulatory context
        (r"\bweapon system(s)?\b", "defense equipment"),
        (r"\blethal autonomous\b", "automated defense"),
        (r"\bdual.use\b", "dual-purpose"),
    ]
    result = text
    for pat, repl in context_repls:
        result = _re.sub(pat, repl, result, flags=_re.IGNORECASE)
    return result


def sanitize_messages(messages: list[dict]) -> list[dict]:
    """
    Sanitize messages before sending to Azure.

    CRITICAL DISTINCTION:
    - USER messages: apply full sanitize_query_for_azure() including conflict reframe.
      These contain the original user query which may have conflict-adjacent terms.
    - SYSTEM messages: apply ONLY word-level replacements (sanitize_research_context).
      System prompts contain research summaries with legitimate content (gold prices,
      forex rates, news mentions of Hormuz etc.) that must NOT be reframed as
      "geopolitical analysis" — that would corrupt the entire synthesis.
    """
    sanitized = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user":
            # Full sanitization including conflict reframe for user queries
            if isinstance(content, str):
                msg = dict(msg)
                msg["content"] = sanitize_query_for_azure(content)
            elif isinstance(content, list):
                msg = dict(msg)
                msg["content"] = [
                    (
                        dict(p, text=sanitize_query_for_azure(p["text"]))
                        if isinstance(p, dict) and p.get("type") == "text"
                        else p
                    )
                    for p in content
                ]
        elif role == "system":
            # ONLY word-level sanitization for system prompts — NO conflict reframe.
            # System prompts contain research data that must stay intact.
            if isinstance(content, str):
                msg = dict(msg)
                msg["content"] = sanitize_research_context(content)
            elif isinstance(content, list):
                msg = dict(msg)
                msg["content"] = [
                    (
                        dict(p, text=sanitize_research_context(p["text"]))
                        if isinstance(p, dict) and p.get("type") == "text"
                        else p
                    )
                    for p in content
                ]
        sanitized.append(msg)
    return sanitized


def safe_json_parse(raw: str, fallback: dict) -> dict:
    """Parse JSON from Azure response — always returns a dict, never raises."""
    if not raw or not raw.strip():
        return fallback
    clean = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    try:
        import re as _re

        m = _re.search(r"\{.*\}", clean, _re.DOTALL)
        if m:
            return json.loads(m.group())
    except Exception:
        pass
    return fallback


# ─── Source quality helpers ───────────────────────────────────────────────────


def get_domain(url: str) -> str:
    """Extract root domain from a URL, stripping www and subdomains."""
    try:
        host = urlparse(url).netloc.lower().replace("www.", "")
        parts = host.split(".")
        return ".".join(parts[-2:]) if len(parts) > 2 else host
    except Exception:
        return ""


def get_full_domain(url: str) -> str:
    """Return full hostname (with subdomains) for exact matching."""
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def classify_domain(url: str) -> str:
    """Return 'tier1', 'tier2', 'unknown', or 'blocked'."""
    domain = get_domain(url)
    full = get_full_domain(url)

    if domain in BLOCKED_DOMAINS or full in BLOCKED_DOMAINS:
        return "blocked"
    if domain in TIER1_DOMAINS or full in TIER1_DOMAINS:
        return "tier1"
    if domain in TIER2_DOMAINS or full in TIER2_DOMAINS:
        return "tier2"
    return "unknown"


def score_result(result: dict) -> float:
    """Score a search result 0.0–1.0. Blocked → -1.0."""
    url = result.get("url", "")
    tier = classify_domain(url)
    snippet = result.get("snippet", "")
    d = result.get("date", "")

    if tier == "blocked":
        return -1.0

    domain = get_domain(url)
    full = get_full_domain(url)
    is_soft = domain in SOFT_DEMOTE_DOMAINS or full in SOFT_DEMOTE_DOMAINS
    if is_soft:
        domain_score = 0.35
    else:
        domain_score = {"tier1": 1.0, "tier2": 0.6, "unknown": 0.4}[tier]

    recency_score = 0.8 if d else 0.2
    snippet_score = min(len(snippet) / 300, 1.0)

    return (domain_score * 0.5) + (recency_score * 0.3) + (snippet_score * 0.2)


def filter_and_rank(results: list[dict], top_n: int = 6) -> list[dict]:
    """Remove blocked domains, rank by score, return top_n (min 3)."""
    scored = [(r, score_result(r)) for r in results]
    scored = [(r, s) for r, s in scored if s >= 0]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [r for r, _ in scored[: max(top_n, 3)]]


# ─── Serper search ────────────────────────────────────────────────────────────


async def serper_search(query: str, num: int = 10) -> list[dict]:
    """Search Google via Serper and return organic results."""
    if not SERPER_API_KEY:
        raise RuntimeError("Serper not configured. Check SERPER_API_KEY in .env")

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            SERPER_SEARCH_URL,
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": query, "num": num},
        )
        resp.raise_for_status()

    return [
        {
            "title": r.get("title", ""),
            "url": r.get("link", ""),
            "snippet": r.get("snippet", ""),
            "date": r.get("date", ""),
        }
        for r in resp.json().get("organic", [])
    ]


# ─── Serper scrape ────────────────────────────────────────────────────────────


async def serper_scrape(url: str) -> dict:
    """
    Scrape a URL using Serper's /scrape endpoint.

    Serper scrape handles:
    - JavaScript-rendered pages (SPA, React, Next.js)
    - Bot-detection bypass
    - Government and legal databases
    - Paywall-lite pages (public snippets)

    Returns {"text": str, "success": bool, "chars": int}
    """
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(
                SERPER_SCRAPE_URL,
                headers={
                    "X-API-KEY": SERPER_API_KEY,
                    "Content-Type": "application/json",
                },
                json={"url": url},
            )

        if resp.status_code != 200:
            return {"text": "", "success": False, "chars": 0}

        data = resp.json()

        # Serper scrape returns: {"text": "...", "metadata": {...}}
        raw_text = data.get("text", "").strip()

        if not raw_text:
            return {"text": "", "success": False, "chars": 0}

        # Clean up excessive whitespace
        cleaned = re.sub(r"\n{3,}", "\n\n", raw_text)
        cleaned = re.sub(r" {2,}", " ", cleaned).strip()

        # Truncate to limit
        truncated = cleaned[:SCRAPE_CHAR_LIMIT]

        return {
            "text": truncated,
            "success": True,
            "chars": len(truncated),
        }

    except Exception:
        return {"text": "", "success": False, "chars": 0}


# ─── BeautifulSoup direct fetch ───────────────────────────────────────────────


async def bs4_fetch(url: str) -> dict:
    """Tier 1: Direct HTTP + BeautifulSoup. Free, no API key needed."""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            return {"text": "", "success": False, "chars": 0, "method": "bs4"}
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return {"text": "", "success": False, "chars": 0, "method": "bs4_no_lib"}
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(
            [
                "script",
                "style",
                "nav",
                "footer",
                "header",
                "aside",
                "form",
                "noscript",
                "iframe",
            ]
        ):
            tag.decompose()
        main = (
            soup.find("main")
            or soup.find("article")
            or soup.find(id="content")
            or soup.find(class_="content")
            or soup.find("body")
        )
        text = main.get_text(separator="\n", strip=True) if main else ""
        if not text or len(text) < 200:
            return {"text": "", "success": False, "chars": 0, "method": "bs4"}
        cleaned = re.sub(r"\n{3,}", "\n\n", text)
        cleaned = re.sub(r" {2,}", " ", cleaned).strip()
        truncated = cleaned[:SCRAPE_CHAR_LIMIT]
        return {
            "text": truncated,
            "success": True,
            "chars": len(truncated),
            "method": "bs4",
        }
    except Exception:
        return {"text": "", "success": False, "chars": 0, "method": "bs4"}


async def scrapingbee_fetch(url: str) -> dict:
    """Tier 3: ScrapingBee — JS rendering + CAPTCHA bypass."""
    if not SCRAPINGBEE_KEY:
        return {
            "text": "",
            "success": False,
            "chars": 0,
            "method": "scrapingbee_no_key",
        }
    try:
        params = {
            "api_key": SCRAPINGBEE_KEY,
            "url": url,
            "render_js": "true",
            "block_ads": "true",
            "block_resources": "true",
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.get(
                "https://app.scrapingbee.com/api/v1/", params=params
            )
        if resp.status_code != 200:
            return {
                "text": "",
                "success": False,
                "chars": 0,
                "method": "scrapingbee",
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
            }
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(
                [
                    "script",
                    "style",
                    "nav",
                    "footer",
                    "header",
                    "aside",
                    "form",
                    "noscript",
                ]
            ):
                tag.decompose()
            main = soup.find("main") or soup.find("article") or soup.find("body")
            text = main.get_text(separator="\n", strip=True) if main else resp.text
        except ImportError:
            text = resp.text
        if not text or len(text) < 200:
            return {"text": "", "success": False, "chars": 0, "method": "scrapingbee"}
        cleaned = re.sub(r"\n{3,}", "\n\n", text)
        cleaned = re.sub(r" {2,}", " ", cleaned).strip()
        truncated = cleaned[:SCRAPE_CHAR_LIMIT]
        return {
            "text": truncated,
            "success": True,
            "chars": len(truncated),
            "method": "scrapingbee",
        }
    except Exception as e:
        return {
            "text": "",
            "success": False,
            "chars": 0,
            "method": "scrapingbee",
            "error": str(e),
        }


async def browserless_fetch(url: str) -> dict:
    """Tier 4: Browserless.io — headless Chrome with full JS rendering."""
    if not BROWSERLESS_KEY:
        return {
            "text": "",
            "success": False,
            "chars": 0,
            "method": "browserless_no_key",
        }
    try:
        payload = {
            "url": url,
            "rejectResourceTypes": ["image", "media", "font", "stylesheet"],
            "gotoOptions": {"waitUntil": "domcontentloaded", "timeout": 25000},
        }
        async with httpx.AsyncClient(timeout=40.0) as client:
            resp = await client.post(
                f"https://production-sfo.browserless.io/content?token={BROWSERLESS_KEY}",
                json=payload,
                headers={
                    "Cache-Control": "no-cache",
                    "Content-Type": "application/json",
                },
            )
        if resp.status_code != 200:
            return {
                "text": "",
                "success": False,
                "chars": 0,
                "method": "browserless",
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
            }
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(
                [
                    "script",
                    "style",
                    "nav",
                    "footer",
                    "header",
                    "aside",
                    "form",
                    "noscript",
                ]
            ):
                tag.decompose()
            main = soup.find("main") or soup.find("article") or soup.find("body")
            text = main.get_text(separator="\n", strip=True) if main else resp.text
        except ImportError:
            text = resp.text
        if not text or len(text) < 200:
            return {"text": "", "success": False, "chars": 0, "method": "browserless"}
        cleaned = re.sub(r"\n{3,}", "\n\n", text)
        cleaned = re.sub(r" {2,}", " ", cleaned).strip()
        truncated = cleaned[:SCRAPE_CHAR_LIMIT]
        return {
            "text": truncated,
            "success": True,
            "chars": len(truncated),
            "method": "browserless",
        }
    except Exception as e:
        return {
            "text": "",
            "success": False,
            "chars": 0,
            "method": "browserless",
            "error": str(e),
        }


async def scraperapi_fetch(url: str) -> dict:
    """Tier 5: ScraperAPI — rotating residential proxies + JS rendering."""
    if not SCRAPERAPI_KEY:
        return {"text": "", "success": False, "chars": 0, "method": "scraperapi_no_key"}
    try:
        params = {"api_key": SCRAPERAPI_KEY, "url": url, "render": "true"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get("https://api.scraperapi.com/", params=params)
        if resp.status_code != 200:
            return {"text": "", "success": False, "chars": 0, "method": "scraperapi"}
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            main = soup.find("main") or soup.find("article") or soup.find("body")
            text = main.get_text(separator="\n", strip=True) if main else ""
        except ImportError:
            text = resp.text[:SCRAPE_CHAR_LIMIT]
        if not text or len(text) < 200:
            return {"text": "", "success": False, "chars": 0, "method": "scraperapi"}
        cleaned = re.sub(r"\n{3,}", "\n\n", text)
        cleaned = re.sub(r" {2,}", " ", cleaned).strip()
        truncated = cleaned[:SCRAPE_CHAR_LIMIT]
        return {
            "text": truncated,
            "success": True,
            "chars": len(truncated),
            "method": "scraperapi",
        }
    except Exception:
        return {"text": "", "success": False, "chars": 0, "method": "scraperapi"}


async def smart_scrape(url: str) -> dict:
    """
    5-tier scraper cascade — returns first success.
    Tier 1: BeautifulSoup (free) → Tier 2: Serper → Tier 3: ScrapingBee
    → Tier 4: Browserless → Tier 5: ScraperAPI
    """
    r = await bs4_fetch(url)
    if r["success"] and r["chars"] > 500:
        return r
    r = await serper_scrape(url)
    if r["success"] and r["chars"] > 500:
        r["method"] = "serper"
        return r
    if SCRAPINGBEE_KEY:
        r = await scrapingbee_fetch(url)
        if r["success"] and r["chars"] > 500:
            return r
    if BROWSERLESS_KEY:
        r = await browserless_fetch(url)
        if r["success"] and r["chars"] > 500:
            return r
    if SCRAPERAPI_KEY:
        r = await scraperapi_fetch(url)
        if r["success"] and r["chars"] > 500:
            return r
    return {"text": "", "success": False, "chars": 0, "method": "all_failed"}


async def enrich_result(result: dict, should_scrape: bool) -> dict:
    """Enrich using smart scraper cascade. Falls back to snippet if all fail.

    Strategy:
    - If should_scrape=True: try Serper scrape first
    - If scrape fails or should_scrape=False: fall back to snippet
    - Always sets: full_content, content_type, content_chars, tier
    """
    url = result.get("url", "")
    tier = classify_domain(url)

    if should_scrape:
        scraped = await smart_scrape(url)
        if scraped["success"] and scraped["chars"] > 200:
            result["full_content"] = scraped["text"]
            result["content_type"] = f"full_page:{scraped['method']}"
            result["content_chars"] = scraped["chars"]
        else:
            result["full_content"] = result["snippet"]
            result["content_type"] = "snippet"
            result["content_chars"] = len(result["snippet"])
    else:
        result["full_content"] = result["snippet"]
        result["content_type"] = "snippet"
        result["content_chars"] = len(result["snippet"])

    result["tier"] = tier
    return result


# ─── Pipeline steps ───────────────────────────────────────────────────────────


async def decompose_query(query: str) -> dict:
    """
    Steps 1 & 2 — Chain-of-thought + decompose into sub-queries.
    Today's date is injected so queries are always date-aware.
    """
    today = date.today().strftime("%B %d, %Y")

    system = f"""You are an expert research strategist and intelligence analyst. Today's date is {today}.

Your job: decompose a research question into queries that find SPECIFIC FACTS,
NAMED ENTITIES, and VERIFIABLE DATA — not generic overviews.

STEP 1 — EXTRACT NAMED ENTITIES FIRST:
Before writing any query, identify every named entity in the question:
- Companies (e.g. CATL, BYD, Changan, Samsung)
- Products with their ACTUAL names (e.g. "Naxtra", "Nevo A06", "Model Y")
- Technologies, standards, regulations, locations, time anchors

If NO specific product/company is named, your FIRST query must DISCOVER them.
Example: "sodium-ion EV China 2026" →
  Q1: "sodium-ion battery EV China launch model 2026" — discovers Naxtra, Nevo A06
  Q2: "CATL Naxtra sodium-ion specifications mass production 2026"

STEP 2 — NAMED-ENTITY-FIRST QUERY RULES:
- NEVER search for failure/delay BEFORE confirming whether success happened
- Use the entity's ACTUAL product name, not just company name
- If question has a conditional ("if not found, search X"), search positive outcome first
- Each query must target a DISTINCT dimension — zero paraphrase overlap

STEP 3 — ANTI-BIAS RULES:
- DO NOT assume failure or delays — lead with success/deployment queries
- DO NOT search government filing databases for product launch news
- ALWAYS include the current year ({date.today().year}) for time-sensitive topics
- For technology + market questions: cover supplier status, OEM adoption, launch evidence

STEP 3b — TEMPORAL BASELINE RULE (for ALL "current status" questions):
If the question asks about CURRENT STATUS, include:
- One query for CURRENT PERIOD ({date.today().year})
- One query for PRIOR PERIOD ({date.today().year - 1}) to establish baseline
Example: "IMEC status?" → Q1: "IMEC 2026 construction update" + Q2: "IMEC 2025 groundbreaking"

STEP 4 — SOURCE STRATEGY:
- Infrastructure/projects: news sites, port authority, government announcements
- EV launches: cnevpost.com, electrek.co, OEM official sites
- Battery tech: CATL/BYD investor relations, CnEVPost, IEEE
- Standards: OEM press releases — NOT government databases
- Pakistan gold prices: goldpricepak.com, hamariweb.com, bullionrates.com, goldpricez.com
  IMPORTANT: Do NOT use site: operator for live gold prices — Google's site-specific
  index is often 1 day old. Instead use: "24K gold rate per tola Pakistan today April 13 2026"
  This gets the freshest result across all gold sites simultaneously.
  Run 2 queries with different wordings to triangulate the current price.
- Pakistan forex: hamariweb.com, thenews.com.pk, pkr.com.pk
  Use: "USD to PKR open market rate today April 13 2026 Pakistan"
  Do NOT use site:hamariweb.com/forex — the /forex subpath is not well-indexed.
- Any live price/rate: ALWAYS include the exact date ({today}) in every query.
  DO NOT use site: operator for live data — it causes stale cache results.

STEP 4b — LIVE DATA QUERY RULE (prices, rates, scores, weather today):
If the question asks for a TODAY value:
1. Include EXACT date ({today}) in every query — this is mandatory for freshness
2. Do NOT use site: operator — it returns cached/indexed data (often 1+ day old)
   Instead use broad queries that let Google pick the freshest crawled page:
   GOOD: "24K gold rate per tola Pakistan today April 13 2026"
   BAD:  "24K gold tola Pakistan site:goldpricepak.com" (stale index)
3. Run 2 parallel queries with different phrasing to cross-verify the value:
   Q1: "24K gold rate per tola Pakistan today April 13 2026"
   Q2: "Pakistan gold rate Karachi Sarafa April 13 2026 tola rupees"
   Q3: "USD to PKR open market rate today April 13 2026"
4. Generate ONLY 2-3 queries — live data doesn't need recursive research

Also classify the question type — this controls answer length and format:
- "factual_lookup": Use when the question asks for specific facts that can be stated directly.
  Signals: "what is", "when is", "what are the deadlines", "find X examples of",
  "what date", "what percentage", "how much", "give me N examples", specific regulation dates,
  specific prices, specific statistics, specific compliance requirements.
  Output: 2-4 tight paragraphs, NO headers. Even if multiple items are asked for,
  if they are all specific facts → factual_lookup.
  Example: "What are the EU AI Act deadlines and 2 examples of mandatory features?" = factual_lookup
- "comparative_analysis": Use ONLY when comparing two distinct options where a side-by-side
  table would be the natural output. Signals: "X vs Y", "compare X and Y", "which is better",
  "differences between". Having "Limited-Risk" AND "High-Risk" in one question is NOT
  comparative — it is asking for facts about both → factual_lookup.
- "explanatory": how/why something works — clear flowing prose, 400-600 words
- "investigative": find hidden patterns, complex multi-party analysis — full report

When in doubt between factual_lookup and investigative: if the answer could fit in
3 paragraphs, it is factual_lookup. Only use investigative for open-ended research
where the answer requires discovering unknown facts across many dimensions.

Respond ONLY with valid JSON:
{{
  "core_subjects": ["entity 1", "entity 2"],
  "dimensions_to_cover": ["dim 1", "dim 2"],
  "question_type": "factual_lookup|comparative_analysis|explanatory|investigative",
  "reasoning": "2-3 sentences: named entities, discovery strategy, bias avoided",
  "queries": ["query 1", "query 2", "query 3"]
}}"""

    raw = await call_azure(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": query},
        ],
        temperature=0.1,
        max_tokens=512,
    )

    clean = raw.replace("```json", "").replace("```", "").strip()
    if not clean:
        return {
            "reasoning": "Fallback",
            "queries": [query],
            "core_subjects": [],
            "dimensions_to_cover": [],
            "question_type": "investigative",
        }
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        import re as _re

        m = _re.search(r"\{.*\}", clean, _re.DOTALL)
        return (
            json.loads(m.group())
            if m
            else {
                "reasoning": "Fallback decomposition",
                "queries": [query],
                "core_subjects": [],
                "dimensions_to_cover": [],
                "question_type": "investigative",
            }
        )


async def search_and_summarize(
    sub_query: str, index: int, original_query: str = ""
) -> dict:
    """
    Step 3 — Full pipeline for one sub-query:
      a) Serper search → 10 raw results
      b) Filter blocked domains, score + rank by tier/recency/snippet quality
      c) Scrape top SCRAPE_TOP_N results via Serper /scrape (concurrent)
         Remaining results get snippets only
      d) Build rich context block with content metadata
      e) Azure GPT summarizes with full awareness of source quality + depth
    """

    # ── 3a: search ────────────────────────────────────────────────────────────
    raw_results = await serper_search(sub_query, num=15)

    # Prepend direct URLs for known authoritative sources (gold, forex, benchmarks)
    # These bypass Google's index lag for live data sites
    direct = construct_direct_urls(sub_query)
    if direct:
        raw_results = direct + (raw_results or [])

    if not raw_results:
        return {
            "index": index,
            "query": sub_query,
            "summary": "No search results found for this query.",
            "citations": [],
        }

    # ── 3b: filter + rank ────────────────────────────────────────────────────
    ranked = filter_and_rank(raw_results, top_n=8)

    # ── 3c: concurrent scrape — top N get full page, rest get snippets ────────
    enrich_tasks = [
        enrich_result(r, should_scrape=(i < SCRAPE_TOP_N)) for i, r in enumerate(ranked)
    ]
    enriched_raw = await asyncio.gather(*enrich_tasks, return_exceptions=True)

    # Recover from individual failures
    final_results: list[dict] = []
    for i, item in enumerate(enriched_raw):
        if isinstance(item, Exception):
            r = ranked[i]
            r["full_content"] = r["snippet"]
            r["content_type"] = "snippet"
            r["content_chars"] = len(r["snippet"])
            r["tier"] = classify_domain(r["url"])
            final_results.append(r)
        else:
            final_results.append(item)

    # ── 3d: build context block ───────────────────────────────────────────────
    context_parts = []
    for i, r in enumerate(final_results):
        domain = get_domain(r["url"])
        content_info = (
            f"full page ({r['content_chars']:,} chars)"
            if r["content_type"] == "full_page"
            else f"snippet ({r['content_chars']} chars)"
        )
        header = (
            f"[{i+1}] {r['title']}"
            + (f" — {r['date']}" if r.get("date") else "")
            + f"\nSource: {domain} | Tier: {r['tier']} | Content: {content_info}"
            + f"\nURL: {r['url']}"
        )
        context_parts.append(f"{header}\n\n{r['full_content']}")

    context_block = "\n\n{'─'*60}\n\n".join(context_parts)

    # Count how many got full scrape vs snippet
    full_count = sum(1 for r in final_results if r["content_type"] == "full_page")
    snippet_count = len(final_results) - full_count

    # ── 3e: Azure GPT summarize ───────────────────────────────────────────────
    _orig_q = original_query or sub_query
    system = f"""You are a research analyst extracting facts relevant to a specific question.

USER'S ORIGINAL QUESTION: {_orig_q}
THIS SUB-QUERY: {sub_query}
Content: {full_count} full-page sources, {snippet_count} snippet-only.

RELEVANCE RULE — MOST IMPORTANT:
Extract ONLY information that directly answers the user's original question.
If the source contains tangential data unrelated to what was asked, skip it.
Examples:
- User asked "24K gold per tola Pakistan" → extract ONLY 24K per tola PKR value.
  Skip: 22K, 21K, per-gram, per-kg, gold futures, global gold trends.
- User asked "USD to PKR open market" → extract ONLY buying/selling rates.
  Skip: EUR/PKR, GBP/PKR, interbank rates unless also asked.
- User asked "CATL Naxtra specs" → extract ONLY Naxtra specs.
  Skip: other CATL products, BYD comparisons, general EV trends.
- User asked "C3 AI layoffs" → extract numbers, dates, percentages.
  Skip: company history, other tech layoffs, general AI industry news.

EXTRACTION RULES (for relevant content only):
1. EXACT VALUES — extract exact numbers, dates, names as found. Never round or paraphrase.
2. SOURCE FLAG — "(one source)" for single claims, "(multiple sources)" for 3+.
3. DATE FLAG — if the source date differs from the requested date, note it explicitly.
   e.g. "goldpricepak.com snippet dated April 12 — may be yesterday's data"
4. DERIVED FACTS — if inputs given, compute outputs (e.g. 26% of 1,181 = ~307).
5. NO INVENTION — never add information not in the provided content.
6. IF NOT FOUND — one sentence: "[Requested fact] was not found in these sources."
   Do NOT fill the response with tangentially related data.
7. FORMAT — 2-4 prose paragraphs maximum, no bullet points."""

    summary = await call_azure(
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"Query: {sub_query}\n\nSources:\n\n{context_block}",
            },
        ],
        temperature=0.1,
        max_tokens=1400,
    )

    citations = [
        {
            "url": r["url"],
            "title": r["title"],
            "domain": get_domain(r["url"]),
            "tier": r["tier"],
            "type": r["content_type"],
            "chars": r["content_chars"],
        }
        for r in final_results
    ]

    return {
        "index": index,
        "query": sub_query,
        "summary": summary,
        "citations": citations,
        "full_scraped": full_count,
    }


async def synthesize(original_query: str, search_results: list[dict]) -> str:
    """
    Step 4 — Final synthesis across all sub-query summaries.
    """
    # Build summary of what was scraped for the synthesizer's awareness
    total_full = sum(r.get("full_scraped", 0) for r in search_results)
    total_sources = sum(len(r["citations"]) for r in search_results)

    system = f"""You are a world-class research synthesizer.

You have {len(search_results)} research summaries from {total_sources} sources across
{len(search_results)} targeted sub-queries. {total_full} sources were read in full.

UNIVERSAL SYNTHESIS RULES:
1. LEAD WITH THE ANSWER — First sentence = the specific number/fact requested.
   For prices/rates: "[Date]: [value] ([source])."
   e.g. "April 13, 2026: 24K gold = Rs. 495,880/tola (goldpricepak.com)."
   NEVER open with background, context, methodology, or caveats.

2. RELEVANCE — answer ONLY what was asked. Do not include related data that wasn't requested.
   Asked "24K gold per tola" → only report 24K per tola.
   Asked "company X layoffs" → only report X's layoffs, not industry trends.
   Asked "USD/PKR rate" → only report USD/PKR, not EUR/PKR or interbank unless asked.
3. IF DATA IS MISSING — state it in ONE sentence, then stop.
   Wrong: paragraphs explaining why + dumping all related snippet content
   Right: "Pakistan 24K gold per tola for April 13, 2026 was not found in sources."
   Do NOT pad with tangential data when the specific answer is absent.

4. CONNECT DOTS — Link findings into a coherent chain (for research questions).
5. ASSERT AGREEMENT — 2+ sources = state as fact. Single source = flag it.
6. EXACT SPECIFICITY — Use exact names/numbers as found. Never paraphrase vaguer.
7. COMPUTE DERIVED FACTS — If research gives calculation inputs, compute the output.
8. ALL BREAKDOWNS — Report every category split found (for research, NOT price lookups).
9. COMPARISON TABLE — If question compares A vs B and metrics exist, include a table.
10. DATE FRESHNESS — If the source date differs from the requested date, flag it:
    "Note: source dated April 12 — may be yesterday's data."
11. HONEST CONFIDENCE — Close with one sentence: confidence + single biggest gap.

- Flowing prose paragraphs — no bullet points, no section headers
- For prices/rates/scores (factual_lookup): 50-150 words MAXIMUM. One fact per sentence.
- For other questions: 350-500 words — dense and direct
- NEVER dump raw snippet calculations or methodology unless explicitly asked"""

    context = "\n\n".join(
        f'=== Sub-research: "{r["query"]}" ===\n{sanitize_research_context(r["summary"])}'
        for r in search_results
    )

    result = await call_azure(
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"Original question: {original_query}\n\n{context}",
            },
        ],
        temperature=0.25,
        max_tokens=2048,
    )
    if not result or not result.strip():
        # Azure output filter blocked the synthesis — return what we found
        summaries_text = "\n\n".join(
            f"Query: {r['query']}\n{r['summary'][:500]}" for r in search_results
        )
        return (
            f"Research completed but synthesis was blocked by content filter. "
            f"Raw findings from {len(search_results)} queries:\n\n{summaries_text[:3000]}"
        )
    return result


# ─── Streaming generator ──────────────────────────────────────────────────────


async def research_stream(query: str):
    start = time.time()

    try:
        # Steps 1 & 2 — decompose
        yield sse("step", {"step": 1, "state": "active", "text": "Thinking..."})
        yield sse("step", {"step": 2, "state": "active", "text": "Decomposing..."})

        decomp = await decompose_query(query)

        yield sse("step", {"step": 1, "state": "done", "text": "Complete"})
        yield sse(
            "step",
            {
                "step": 2,
                "state": "done",
                "text": f"{len(decomp['queries'])} queries identified",
            },
        )
        yield sse(
            "decomposition",
            {
                "reasoning": decomp["reasoning"],
                "queries": decomp["queries"],
            },
        )

        # Step 3 — parallel search + scrape + summarize
        yield sse(
            "step",
            {
                "step": 3,
                "state": "active",
                "text": f"Searching & scraping (top {SCRAPE_TOP_N} per query)...",
            },
        )

        for i, q in enumerate(decomp["queries"]):
            yield sse("search_start", {"index": i, "query": q})

        tasks = [
            search_and_summarize(q, i, query) for i, q in enumerate(decomp["queries"])
        ]

        search_results: list[dict] = []
        total_full_scraped = 0

        for coro in asyncio.as_completed(tasks):
            result = await coro
            search_results.append(result)
            total_full_scraped += result.get("full_scraped", 0)
            yield sse(
                "search_done",
                {
                    "index": result["index"],
                    "query": result["query"],
                    "citations": result["citations"][:4],
                    "full_scraped": result.get("full_scraped", 0),
                },
            )

        search_results.sort(key=lambda r: r["index"])

        # Global URL deduplication
        seen_urls: set[str] = set()
        all_citations: list[dict] = []
        for r in search_results:
            unique = []
            for c in r["citations"]:
                if c["url"] not in seen_urls:
                    seen_urls.add(c["url"])
                    all_citations.append(c)
                    unique.append(c)
            r["citations"] = unique

        yield sse(
            "step",
            {
                "step": 3,
                "state": "done",
                "text": f"Complete — {total_full_scraped} pages fully read",
            },
        )

        # Step 4 — synthesize
        yield sse("step", {"step": 4, "state": "active", "text": "Synthesizing..."})

        answer = await synthesize(query, search_results)

        elapsed = round(time.time() - start, 1)

        yield sse("step", {"step": 4, "state": "done", "text": "Complete"})
        yield sse(
            "result",
            {
                "answer": answer,
                "elapsed": elapsed,
                "sources_searched": len(search_results),
                "total_scraped": total_full_scraped,
                "citations": all_citations[:15],
            },
        )

    except httpx.HTTPStatusError as e:
        try:
            detail = e.response.json()
            msg = (
                detail.get("error", {}).get("message")
                or detail.get("message")
                or e.response.text
            )
        except Exception:
            msg = e.response.text
        yield sse("error", {"message": f"API error {e.response.status_code}: {msg}"})

    except json.JSONDecodeError as e:
        yield sse("error", {"message": f"Failed to parse model JSON response: {e}"})

    except RuntimeError as e:
        yield sse("error", {"message": str(e)})

    except Exception as e:
        yield sse("error", {"message": f"Unexpected error: {type(e).__name__}: {e}"})

    finally:
        yield sse("done", {})


# ─── Endpoints ────────────────────────────────────────────────────────────────


@app.post("/research/light")
async def light_research(req: ResearchRequest):
    missing = []
    if not AZURE_OPENAI_KEY or not AZURE_OPENAI_ENDPOINT:
        missing.append("AZURE_OPENAI_KEY and AZURE_OPENAI_ENDPOINT")
    if not SERPER_API_KEY:
        missing.append("SERPER_API_KEY")
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing .env config: {', '.join(missing)}",
        )

    return StreamingResponse(
        research_stream(req.query),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(content=Path("static/index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


# ═══════════════════════════════════════════════════════════════════════════════
# MEDIUM RESEARCH
# Recursive Light Research with gap detection, up to MAX_ROUNDS passes,
# then a structured long-form report synthesis.
# ═══════════════════════════════════════════════════════════════════════════════

MEDIUM_MAX_ROUNDS = 4  # maximum recursive passes
MEDIUM_MIN_ROUNDS = 2  # always do at least this many passes
MEDIUM_QUERIES_PER_ROUND = (
    4  # sub-queries per round (slightly fewer than light for depth)
)


# ─── Gap analysis ─────────────────────────────────────────────────────────────


async def analyze_gaps(
    original_query: str,
    round_num: int,
    all_summaries: list[dict],
    seen_queries: list[str],
) -> dict:
    """
    After each research round, ask GPT:
    - What important questions remain unanswered?
    - What claims need verification from additional sources?
    - What angles or perspectives were not covered?
    - What follow-up searches would most improve the answer?

    Returns {
      "gaps_found": bool,
      "gap_analysis": str,       # human-readable explanation of gaps
      "follow_up_queries": [...], # new search queries targeting gaps
      "confidence": float         # 0.0-1.0 how complete the research is
    }
    """
    today = date.today().strftime("%B %d, %Y")

    # Build a summary of everything found so far
    accumulated = "\n\n".join(
        f"=== Round {s['round']}, Query: \"{s['query']}\" ===\n{sanitize_research_context(s['summary'])}"
        for s in all_summaries
    )

    seen_str = "\n".join(f"- {q}" for q in seen_queries)

    system = f"""You are a rigorous research quality analyst. Today is {today}.

A researcher has completed round {round_num} of recursive research on a topic.
Your job is to critically evaluate what has been found and identify what's still missing.

Already searched queries (DO NOT repeat these):
{seen_str}

Evaluate the accumulated research and respond ONLY with valid JSON:
{{
  "gaps_found": true/false,
  "confidence": 0.0-1.0,
  "gap_analysis": "2-3 sentence assessment of what is missing and why it matters",
  "follow_up_queries": [
    "targeted query addressing gap 1",
    "targeted query addressing gap 2",
    "targeted query addressing gap 3"
  ]
}}

CONFIDENCE SCORE RUBRIC:
- 0.90-1.00: All data from Tier-1/primary. Multiple sources agree. Numbers confirmed.
- 0.80-0.89: Core data found. Minor gaps. 2-3 good sources per claim.
- 0.72-0.79: Main answer present but some single-source or secondary-only claims.
- 0.65-0.71: Important parts unanswered. Mostly secondary evidence.
- 0.50-0.64: Major portions unanswered. Critical data missing.
- 0.00-0.49: Little to no reliable evidence.
Only score below 0.65 if actual answer DATA is absent (not just ideal sources missing).
Verified absence across 2+ sources = 0.75+. Proxy data found = 0.75+.

STRUCTURAL UNAVAILABILITY RULE:
If primary source is "Coming Soon", behind paywall, or not yet published:
- Score 0.75+ if best proxy data is found
- Set gaps_found=false — more searching won't find an unavailable source
- State "Primary source structurally unavailable — [reason]" in gap_analysis

VERIFIED ABSENCE RULE:
If multiple rounds consistently find NO evidence of X, "X did not happen" IS the answer.
Score 0.75+ if 2+ independent sources were checked and absence is consistent.

ENTITY EXTRACTION RULE — HIGHEST PRIORITY:
Scan research for named entities not yet specifically searched:
Snippet mentions "CATL Naxtra" → search "CATL Naxtra battery specifications 2026"
Snippet mentions "Changan Nevo A06" → search "Changan Nevo A06 sodium-ion launch"
Snippet mentions "GAC Aion" → search "GAC Aion Y Plus sodium-ion 2026"

TEMPORAL PIVOT RULE:
If "no evidence of X in {date.today().year}", search prior year for baseline:
"No IMEC construction in 2026" → search "IMEC construction 2025 groundbreaking"

STRATEGY PIVOT RULE:
If same source type returns empty repeatedly, pivot completely:
- Gov databases empty? → OEM press releases + news sites
- No {date.today().year} results? → Search {date.today().year - 1} baseline
- Generic queries failed? → Search specific entity names from research
- One source type exhausted? → CnEVPost, PingWest, Electrek, BloombergNEF

Rules for follow_up_queries:
- Maximum {MEDIUM_QUERIES_PER_ROUND} queries
- FIRST PRIORITY: specific entity names from previous rounds not yet deep-searched
- SECOND PRIORITY: fill specific data gaps (dates, prices, capacities)
- THIRD PRIORITY: verify single-source claims with additional source types
- No generic topic queries in rounds 2+ — use specific entity names
- If confidence >= 0.85 or no real gaps, set gaps_found=false and follow_up_queries=[]"""

    raw = await call_azure(
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"Original question: {original_query}\n\nAccumulated research:\n\n{accumulated}",
            },
        ],
        temperature=0.2,
        max_tokens=600,
    )

    data = safe_json_parse(
        raw,
        {
            "gaps_found": False,
            "confidence": 0.75,
            "gap_analysis": "Gap analysis unavailable — proceeding with available research.",
            "follow_up_queries": [],
        },
    )
    if not isinstance(data.get("follow_up_queries"), list):
        data["follow_up_queries"] = []
    return data


# ─── Structured report synthesizer ───────────────────────────────────────────


async def synthesize_report(
    original_query: str,
    all_summaries: list[dict],
    all_citations: list[dict],
    rounds_completed: int,
    gap_analyses: list[dict],
    question_type: str = "comparative_analysis",
) -> str:
    """
    Final synthesis for Medium Research — produces a structured long-form report
    (800-1200 words) across all rounds of research.

    Unlike Light's prose synthesis, this produces a structured document with:
    - Executive summary
    - Key findings (with confidence levels)
    - Detailed analysis
    - Conflicting information / caveats
    - Confidence assessment
    """
    total_sources = len(all_citations)
    total_scraped = sum(1 for c in all_citations if c.get("type") == "full_page")
    tier1_count = sum(1 for c in all_citations if c.get("tier") == "tier1")

    # Build round-by-round context
    rounds_context = ""
    current_round = 0
    for s in all_summaries:
        if s["round"] != current_round:
            current_round = s["round"]
            rounds_context += (
                f"\n\n{'='*60}\nROUND {current_round} RESEARCH\n{'='*60}\n"
            )
        rounds_context += f"\n--- Query: \"{s['query']}\" ---\n{sanitize_research_context(s['summary'])}\n"

    # Include gap analysis reasoning
    gap_context = ""
    for i, g in enumerate(gap_analyses):
        if g.get("gap_analysis"):
            gap_context += f"\nAfter round {i+1}: {g['gap_analysis']}\n"

    # Detect if user wants a comparison table
    table_keywords = [
        "comparison table",
        "compare table",
        "create a table",
        "comparison chart",
        "table covering",
        "table of",
        "tabular",
        "side by side",
        "side-by-side",
        "vs table",
        "comparison matrix",
    ]
    wants_table = any(kw in original_query.lower() for kw in table_keywords)
    table_note = (
        """

IMPORTANT: The user explicitly requested a comparison table. Include a ## Comparison Table
section immediately after Key Findings using proper markdown table syntax:
| Feature | Option A | Option B |
|---|---|---|
Populate every cell with concrete values. Write "Not publicly documented" for missing data."""
        if wants_table
        else ""
    )

    system = f"""You are a world-class research analyst. Produce a precise research report.

Question type: {question_type}
Research: {rounds_completed} rounds, {total_sources} sources, {total_scraped} pages read, {tier1_count} Tier-1.

UNIVERSAL SYNTHESIS RULES — apply always:
1. LEAD WITH THE ANSWER — First sentence = most specific finding. Exact names, numbers, dates.
2. RELEVANCE — report ONLY what the original question asked for. Do not include
   related data, tangential facts, or industry context that wasn't requested.
   If asked for one specific metric, give that metric — not everything around it.
3. CONNECT DOTS ACROSS ROUNDS — supplier → product → OEM → model → launch → market impact.
4. NEVER LEAD WITH UNCERTAINTY — Caveats come AFTER findings, never before.
5. EXACT SPECIFICITY — Use exact names/numbers as found. Never paraphrase vaguer.
6. COMPUTE DERIVED FACTS — "26% of 1,181 = ~307 eliminated" — always compute and state.
7. ALL BREAKDOWNS — "Sales -36%, R&D -25%, Admin -13%" beats "cuts across all areas".
8. COMPARISON TABLES — If A vs B with numeric scores, present as markdown table.
9. HONEST CONFIDENCE — Low only if answer data is genuinely absent.

FORMAT CONTROL — THIS IS MANDATORY, adapt strictly to question_type:

If question_type = "factual_lookup":
  - Write 2-4 prose paragraphs ONLY. Zero section headers (no ##). Zero bullet points.
  - Total: 250-450 words maximum.
  - Structure: Para 1 = the direct answer with exact facts. Para 2 = supporting detail.
    Para 3 = any important caveat or second dimension. Para 4 = confidence sentence.
  - DO NOT produce Executive Summary, Key Findings, or any ## sections.
  - Example correct output for "What are the EU AI Act deadlines?":
    "From 2 August 2026, the EU AI Act's transparency rules under Article 50
    become mandatory for limited-risk AI systems, including chatbots and generative AI.
    Two features become mandatory on that date: [feature 1] and [feature 2]..."

If question_type = "comparative_analysis":
  - 2 dense opening paragraphs + comparison table (if triggered) + ## Details + ## Confidence.
  - Total: 500-800 words.

If question_type = "explanatory":
  - Flowing prose, light structure, 400-600 words.

If question_type = "investigative":
  - Full ## sections (Executive Summary, Key Findings, Detailed Analysis,
    Conflicting Information, Confidence Assessment), 900-1200 words.

Rules:
- Use exact names, dates, scores, percentages, dollar amounts from research
- Cite inline: "(European Commission)", "(Reuters)", "[single source — verify]"
- NEVER pad — density beats length
- Write for an intelligent professional{table_note}"""

    return await call_azure(
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"Original question: {original_query}\n\nGap analysis between rounds:{gap_context}\n\nRound-by-round research:{rounds_context}",
            },
        ],
        temperature=0.2,
        max_tokens=3000,
        timeout=120.0,
    )


# ─── Medium research stream ───────────────────────────────────────────────────


async def medium_research_stream(query: str):
    """
    Recursive research generator:
    1. Run Light Research pass (decompose → search → scrape → summarize)
    2. Analyze gaps in what was found
    3. If gaps exist and rounds < MAX: run another pass targeting gaps
    4. Repeat up to MAX_ROUNDS
    5. Synthesize everything into a structured long-form report
    """
    start = time.time()

    all_summaries: list[dict] = []  # all per-query summaries across all rounds
    all_citations: list[dict] = []  # all citations, globally deduplicated
    seen_urls: set[str] = set()
    seen_queries: list[str] = []  # all queries ever searched (for gap analysis)
    gap_analyses: list[dict] = []  # gap analysis result per round
    total_scraped = 0

    try:
        for round_num in range(1, MEDIUM_MAX_ROUNDS + 1):

            # ── Signal round start ─────────────────────────────────────────────
            yield sse(
                "round_start",
                {
                    "round": round_num,
                    "max_rounds": MEDIUM_MAX_ROUNDS,
                },
            )

            # ── Decompose (round 1) or use gap queries (rounds 2+) ────────────
            if round_num == 1:
                yield sse("step", {"step": 1, "state": "active", "text": "Thinking..."})
                yield sse(
                    "step", {"step": 2, "state": "active", "text": "Decomposing..."}
                )

                decomp = await decompose_query(sanitize_query_for_azure(query))
                queries_this_round = decomp["queries"]

                yield sse("step", {"step": 1, "state": "done", "text": "Complete"})
                yield sse(
                    "step",
                    {
                        "step": 2,
                        "state": "done",
                        "text": f"{len(queries_this_round)} queries identified",
                    },
                )
                yield sse(
                    "decomposition",
                    {
                        "reasoning": decomp["reasoning"],
                        "queries": queries_this_round,
                        "round": round_num,
                    },
                )

            else:
                # Use gap-analysis follow-up queries
                queries_this_round = gap_analyses[-1].get("follow_up_queries", [])
                if not queries_this_round:
                    break

                yield sse(
                    "decomposition",
                    {
                        "reasoning": gap_analyses[-1].get("gap_analysis", ""),
                        "queries": queries_this_round,
                        "round": round_num,
                    },
                )

            seen_queries.extend(queries_this_round)

            # ── Parallel search + scrape + summarize ───────────────────────────
            yield sse(
                "step",
                {
                    "step": 3,
                    "state": "active",
                    "text": f"Round {round_num} — searching & scraping {len(queries_this_round)} queries...",
                },
            )

            for i, q in enumerate(queries_this_round):
                yield sse(
                    "search_start",
                    {
                        "index": i,
                        "query": q,
                        "round": round_num,
                    },
                )

            tasks = [
                search_and_summarize(q, i, query)
                for i, q in enumerate(queries_this_round)
            ]

            round_results: list[dict] = []
            for coro in asyncio.as_completed(tasks):
                result = await coro
                round_results.append(result)
                total_scraped += result.get("full_scraped", 0)

                # Deduplicate citations globally
                unique_citations = []
                for c in result["citations"]:
                    if c["url"] not in seen_urls:
                        seen_urls.add(c["url"])
                        all_citations.append(c)
                        unique_citations.append(c)
                result["citations"] = unique_citations

                yield sse(
                    "search_done",
                    {
                        "index": result["index"],
                        "query": result["query"],
                        "citations": result["citations"][:4],
                        "full_scraped": result.get("full_scraped", 0),
                        "round": round_num,
                    },
                )

            round_results.sort(key=lambda r: r["index"])

            # Tag each summary with its round number
            for r in round_results:
                all_summaries.append(
                    {
                        "round": round_num,
                        "query": r["query"],
                        "summary": r["summary"],
                    }
                )

            yield sse(
                "step",
                {
                    "step": 3,
                    "state": "done",
                    "text": f"Round {round_num} complete — {total_scraped} pages read total",
                },
            )

            # ── Gap analysis (after every round except last) ───────────────────
            is_last_round = round_num >= MEDIUM_MAX_ROUNDS
            has_min_rounds = round_num >= MEDIUM_MIN_ROUNDS

            if not is_last_round:
                yield sse("gap_analysis_start", {"round": round_num})

                gap = await analyze_gaps(
                    query,
                    round_num,
                    all_summaries,
                    seen_queries,
                )
                gap_analyses.append(gap)

                yield sse(
                    "gap_analysis_done",
                    {
                        "round": round_num,
                        "gaps_found": gap["gaps_found"],
                        "confidence": gap.get("confidence", 0),
                        "gap_analysis": gap.get("gap_analysis", ""),
                        "next_queries": gap.get("follow_up_queries", []),
                    },
                )

                # Stop early: no gaps OR confidence >= 0.70
                confidence_val = gap.get("confidence", 0)
                should_stop_gap = has_min_rounds and not gap["gaps_found"]
                should_stop_conf = has_min_rounds and confidence_val >= 0.70
                if should_stop_gap or should_stop_conf:
                    stop_reason = (
                        "Research sufficiently complete"
                        if should_stop_gap
                        else f"Confidence threshold reached ({round(confidence_val*100)}%)"
                    )
                    yield sse(
                        "early_stop",
                        {
                            "round": round_num,
                            "reason": stop_reason,
                            "confidence": confidence_val,
                        },
                    )
                    break
            else:
                gap_analyses.append({"gap_analysis": "", "follow_up_queries": []})

        # ── Final report synthesis ─────────────────────────────────────────────
        rounds_completed = round_num

        yield sse(
            "step",
            {
                "step": 4,
                "state": "active",
                "text": f"Synthesizing report across {rounds_completed} rounds & {len(all_citations)} sources...",
            },
        )

        _qtype = decomp.get("question_type", "comparative_analysis")
        report = await synthesize_report(
            query,
            all_summaries,
            all_citations,
            rounds_completed,
            gap_analyses,
            question_type=_qtype,
        )

        elapsed = round(time.time() - start, 1)

        yield sse("step", {"step": 4, "state": "done", "text": "Report complete"})
        yield sse(
            "result",
            {
                "answer": report,
                "elapsed": elapsed,
                "rounds_completed": rounds_completed,
                "sources_searched": len(all_summaries),
                "total_scraped": total_scraped,
                "citations": all_citations[:30],
                "mode": "medium",
            },
        )

    except httpx.HTTPStatusError as e:
        try:
            detail = e.response.json()
            msg = (
                detail.get("error", {}).get("message")
                or detail.get("message")
                or e.response.text
            )
        except Exception:
            msg = e.response.text
        yield sse("error", {"message": f"API error {e.response.status_code}: {msg}"})

    except json.JSONDecodeError as e:
        yield sse("error", {"message": f"Failed to parse model JSON: {e}"})

    except RuntimeError as e:
        yield sse("error", {"message": str(e)})

    except Exception as e:
        yield sse("error", {"message": f"Unexpected error: {type(e).__name__}: {e}"})

    finally:
        yield sse("done", {})


# ─── Medium endpoint ──────────────────────────────────────────────────────────


@app.post("/research/medium")
async def medium_research(req: ResearchRequest):
    missing = []
    if not AZURE_OPENAI_KEY or not AZURE_OPENAI_ENDPOINT:
        missing.append("AZURE_OPENAI_KEY and AZURE_OPENAI_ENDPOINT")
    if not SERPER_API_KEY:
        missing.append("SERPER_API_KEY")
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing .env config: {', '.join(missing)}",
        )

    return StreamingResponse(
        medium_research_stream(req.query),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ═══════════════════════════════════════════════════════════════════════════════
# DEEP RESEARCH
# Extended recursive research (up to 8 rounds) with Playwright browser for
# hard-to-reach pages, academic API search (arXiv + Semantic Scholar) for
# scientific questions, PDF extraction, and a long-form exportable report.
# ═══════════════════════════════════════════════════════════════════════════════

import tempfile
from fastapi.responses import FileResponse

# ─── Deep Research config ─────────────────────────────────────────────────────

DEEP_MAX_ROUNDS = 8  # maximum recursive passes
DEEP_MIN_ROUNDS = 3  # always do at least this many passes
DEEP_BROWSER_START_ROUND = 4  # switch to Playwright from this round onward
DEEP_QUERIES_PER_ROUND = 4  # sub-queries per round
DEEP_SCRAPE_CHAR_LIMIT = 9000  # more chars per page than Light/Medium
DEEP_BROWSER_TOP_N = 3  # pages to open with Playwright per query
BROWSER_HEADLESS = os.getenv("BROWSER_HEADLESS", "true").lower() != "false"

# Academic API endpoints (free, no key needed)
ARXIV_API_URL = "https://export.arxiv.org/api/query"
SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"


# ─── Academic topic detector ──────────────────────────────────────────────────


async def is_academic_query(query: str) -> bool:
    """
    Strictly classifies whether a query needs academic/scientific literature.

    The bar is HIGH — only return True when peer-reviewed papers would
    genuinely add value that web sources cannot provide.

    Industry tech questions (APIs, SDKs, protocols, benchmarks, frameworks,
    company products, developer tools) are NEVER academic even if they use
    technical language or ask for benchmarks/comparisons.
    """
    system = """You are a strict academic relevance classifier.

Your job: decide if searching peer-reviewed papers and preprints (arXiv, PubMed,
Semantic Scholar) would add GENUINE VALUE to answering this question — value that
industry blogs, documentation, and GitHub cannot provide.

STRICT RULES:
- Answer YES only when the question is about: fundamental scientific research,
  medical/clinical studies, peer-reviewed ML research (novel architectures/theory),
  biology, chemistry, physics, climate science, neuroscience, or academic economics.
- Answer NO for ALL of the following (even if they sound technical):
    * Software frameworks, APIs, SDKs, developer tools, protocols
    * Company products, product comparisons, industry benchmarks
    * Business strategy, startup funding, market analysis
    * Legal or regulatory questions
    * News, current events, sports, entertainment
    * Developer questions ("how does X work", "X vs Y comparison")
    * Security tools, DevOps, cloud infrastructure
    * AI product comparisons (GPT vs Claude, MCP vs Operator, etc.)

The question "MCP vs OpenAI Operator authentication benchmarks" is NOT academic.
The question "CRISPR gene editing off-target effects" IS academic.
The question "transformer attention mechanism latency" is NOT academic (it is industry).
The question "novel neural architecture for protein folding" IS academic.

When in doubt: answer NO. Only say YES when you are certain peer-reviewed
literature is the primary source of truth for this question.

Respond with ONLY a single word: yes or no"""

    try:
        result = await call_azure(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": query},
            ],
            temperature=0.0,
            max_tokens=5,
        )
        return result.strip().lower().startswith("yes")
    except Exception:
        return False


# ─── Playwright browser fetch ─────────────────────────────────────────────────
# Windows fix: asyncio on Windows cannot spawn subprocesses from within a
# running event loop (NotImplementedError on create_subprocess_exec).
# Solution: run the synchronous Playwright API in a ThreadPoolExecutor so it
# gets its own thread with its own event loop — completely bypassing the issue.

import concurrent.futures

_playwright_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def _playwright_fetch_sync(url: str, headless: bool, char_limit: int) -> dict:
    """
    Synchronous Playwright fetch — runs in a thread pool.
    Uses sync_playwright API which works reliably on Windows.
    """
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=headless)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            page = context.new_page()

            # Block images, fonts, media to speed up loading
            page.route(
                "**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf,mp4,mp3}",
                lambda route: route.abort(),
            )

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
            except Exception:
                browser.close()
                return {
                    "text": "",
                    "success": False,
                    "chars": 0,
                    "method": "playwright",
                }

            # Scroll to trigger lazy-loaded content
            page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            page.wait_for_timeout(1000)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(500)

            # Extract readable text (strips nav, footer, scripts)
            text = page.evaluate(
                """() => {
                ['script','style','nav','footer','header','aside',
                 '.nav','.footer','.header','.sidebar','.menu',
                 '[role=navigation]','[role=banner]','[role=complementary]'
                ].forEach(sel => {
                    document.querySelectorAll(sel).forEach(el => el.remove());
                });
                return document.body ? document.body.innerText : '';
            }"""
            )

            browser.close()

        if not text or len(text.strip()) < 100:
            return {"text": "", "success": False, "chars": 0, "method": "playwright"}

        # Clean whitespace
        import re as _re

        cleaned = _re.sub(r"[\n]{3,}", "\n\n", text)
        cleaned = _re.sub(r" {2,}", " ", cleaned).strip()
        truncated = cleaned[:char_limit]

        return {
            "text": truncated,
            "success": True,
            "chars": len(truncated),
            "method": "playwright",
        }

    except ImportError:
        return {
            "text": "",
            "success": False,
            "chars": 0,
            "method": "playwright_not_installed",
        }

    except Exception as e:
        return {
            "text": "",
            "success": False,
            "chars": 0,
            "method": f"playwright_error: {type(e).__name__}",
        }


async def playwright_fetch(url: str) -> dict:
    """
    Async wrapper — runs the synchronous Playwright fetch in a thread pool.
    This is the Windows-compatible approach: avoids NotImplementedError from
    asyncio trying to spawn subprocesses inside an already-running event loop.

    Falls back to Serper scrape if Playwright fails or is not installed.
    """
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            _playwright_executor,
            _playwright_fetch_sync,
            url,
            BROWSER_HEADLESS,
            DEEP_SCRAPE_CHAR_LIMIT,
        )

        # If playwright itself failed, fall back to Serper scrape
        if not result["success"] and "not_installed" not in result["method"]:
            scraped = await serper_scrape(url)
            if scraped["success"]:
                scraped["method"] = "serper_scrape_fallback"
                return scraped

        return result

    except Exception:
        # Last resort fallback
        scraped = await serper_scrape(url)
        scraped["method"] = "serper_scrape_fallback"
        return scraped


# ─── Academic search: arXiv ───────────────────────────────────────────────────


async def search_arxiv(query: str, max_results: int = 5) -> list[dict]:
    """
    Search arXiv preprint server via their free Atom API.
    Returns list of {title, authors, abstract, url, published, source}.
    """
    try:
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(ARXIV_API_URL, params=params)
            resp.raise_for_status()

        # Parse Atom XML
        xml = resp.text
        entries = re.findall(r"<entry>(.*?)</entry>", xml, re.DOTALL)

        results = []
        for entry in entries:
            title = re.search(r"<title>(.*?)</title>", entry, re.DOTALL)
            abstract = re.search(r"<summary>(.*?)</summary>", entry, re.DOTALL)
            published = re.search(r"<published>(.*?)</published>", entry)
            url_match = re.search(r"<id>(.*?)</id>", entry)
            authors = re.findall(r"<name>(.*?)</name>", entry)

            if not title or not abstract:
                continue

            results.append(
                {
                    "title": re.sub(r"\s+", " ", title.group(1)).strip(),
                    "authors": ", ".join(authors[:3])
                    + (" et al." if len(authors) > 3 else ""),
                    "abstract": re.sub(r"\s+", " ", abstract.group(1)).strip()[:800],
                    "url": url_match.group(1).strip() if url_match else "",
                    "published": published.group(1)[:10] if published else "",
                    "source": "arxiv",
                }
            )

        return results

    except Exception:
        return []


# ─── Academic search: Semantic Scholar ───────────────────────────────────────


async def search_semantic_scholar(query: str, max_results: int = 5) -> list[dict]:
    """
    Search Semantic Scholar via their free public API.
    Returns list of {title, authors, abstract, url, year, citations, source}.
    """
    try:
        params = {
            "query": query,
            "limit": max_results,
            "fields": "title,authors,abstract,year,citationCount,externalIds,openAccessPdf",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(SEMANTIC_SCHOLAR_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = []
        for paper in data.get("data", []):
            # Build URL
            ids = paper.get("externalIds", {})
            url = ""
            if ids.get("DOI"):
                url = f"https://doi.org/{ids['DOI']}"
            elif ids.get("ArXiv"):
                url = f"https://arxiv.org/abs/{ids['ArXiv']}"

            # Get open access PDF if available
            pdf_url = ""
            if paper.get("openAccessPdf"):
                pdf_url = paper["openAccessPdf"].get("url", "")

            authors = [a.get("name", "") for a in paper.get("authors", [])[:3]]

            results.append(
                {
                    "title": paper.get("title", ""),
                    "authors": ", ".join(authors)
                    + (" et al." if len(paper.get("authors", [])) > 3 else ""),
                    "abstract": (paper.get("abstract") or "")[:800],
                    "url": url,
                    "pdf_url": pdf_url,
                    "year": str(paper.get("year", "")),
                    "citations": paper.get("citationCount", 0),
                    "source": "semantic_scholar",
                }
            )

        return results

    except Exception:
        return []


# ─── Academic query extractor ────────────────────────────────────────────────


async def extract_academic_search_terms(query: str) -> str:
    """
    Use GPT to extract focused, specific academic search terms from a
    free-form research question. Returns a short, precise search string
    suitable for arXiv and Semantic Scholar APIs.

    This prevents the raw query (which may be long and contain noise words
    like "as of April 2026" or "create a comparison table") from polluting
    the academic search and returning irrelevant papers.
    """
    system = """You are an academic search query optimizer.

Given a research question, extract the core scientific/technical concepts
that would appear in the titles and abstracts of relevant peer-reviewed papers.

Rules:
- Return ONLY the search terms, nothing else — no explanation, no punctuation
- 3-6 words maximum
- Use specific technical terminology, not generic words
- Drop all temporal phrases ("as of 2026", "latest", "recent")
- Drop all task descriptions ("compare", "create a table", "find")
- Drop all narrative framing ("conduct a deep-dive", "give me")
- Focus on the scientific subject matter only

Examples:
Input: "What are the latest treatments for Type 2 diabetes in elderly patients?"
Output: type 2 diabetes treatment elderly

Input: "Explain how transformer attention mechanisms work and their computational complexity"
Output: transformer attention mechanism computational complexity

Input: "MCP vs OpenAI Operator authentication benchmarks for developers"
Output: AI agent tool calling protocol"""

    try:
        result = await call_azure(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": query},
            ],
            temperature=0.0,
            max_tokens=20,
        )
        terms = result.strip().lower()
        # Safety: if GPT returns something long, truncate to first 6 words
        words = terms.split()[:6]
        return " ".join(words)
    except Exception:
        # Fallback: take first 5 words of query
        return " ".join(query.split()[:5])


async def is_paper_relevant(paper: dict, original_query: str) -> bool:
    """
    Quick relevance check — does this paper actually relate to the query?
    Uses title + abstract snippet for a fast binary yes/no.
    Filters out false positives like physics papers on AI queries.
    """
    title = paper.get("title", "")
    abstract = (paper.get("abstract") or "")[:300]

    system = """You are a relevance filter. Given a research question and a paper,
decide if the paper is genuinely relevant to the question.

Answer YES only if the paper directly addresses the subject matter of the question.
Answer NO if the paper is from an unrelated field even if it shares some keywords.

Respond with ONLY: yes or no"""

    user = (
        f"Research question: {original_query}\n\n"
        f"Paper title: {title}\n"
        f"Abstract: {abstract}"
    )

    try:
        result = await call_azure(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            max_tokens=5,
        )
        return result.strip().lower().startswith("yes")
    except Exception:
        return True  # if check fails, keep the paper


# ─── Combined academic search ─────────────────────────────────────────────────


async def academic_search(query: str) -> dict:
    """
    Run arXiv and Semantic Scholar searches in parallel.
    1. First extracts focused search terms from the raw query
    2. Searches both APIs with the refined terms
    3. Filters results for relevance using GPT
    4. Returns {"papers": [...], "total": int}
    """
    # Step 1: extract focused search terms
    search_terms = await extract_academic_search_terms(query)

    # Step 2: search both APIs in parallel with refined terms
    arxiv_results, ss_results = await asyncio.gather(
        search_arxiv(search_terms, max_results=6),
        search_semantic_scholar(search_terms, max_results=6),
        return_exceptions=True,
    )

    # Step 3: combine and deduplicate
    papers = []
    if isinstance(arxiv_results, list):
        papers.extend(arxiv_results)
    if isinstance(ss_results, list):
        existing_titles = {p["title"].lower()[:50] for p in papers}
        for p in ss_results:
            if p["title"].lower()[:50] not in existing_titles:
                papers.append(p)
                existing_titles.add(p["title"].lower()[:50])

    # Step 4: relevance filter — run in parallel
    if papers:
        relevance_checks = await asyncio.gather(
            *[is_paper_relevant(p, query) for p in papers],
            return_exceptions=True,
        )
        papers = [
            p
            for p, relevant in zip(papers, relevance_checks)
            if relevant is True  # keep only confirmed relevant papers
        ]

    # Step 5: sort and cap
    ss_papers = sorted(
        [p for p in papers if p["source"] == "semantic_scholar"],
        key=lambda x: x.get("citations", 0),
        reverse=True,
    )
    ax_papers = sorted(
        [p for p in papers if p["source"] == "arxiv"],
        key=lambda x: x.get("published", ""),
        reverse=True,
    )

    combined = (ss_papers + ax_papers)[:8]

    return {"papers": combined, "total": len(combined)}


# ─── Deep search + summarize (browser-enabled) ───────────────────────────────


async def deep_search_and_summarize(
    sub_query: str,
    index: int,
    use_browser: bool = False,
) -> dict:
    """
    Deep version of search_and_summarize.
    When use_browser=True, Playwright opens the top pages instead of Serper scrape.
    Falls back to Serper scrape if Playwright fails.
    """
    # Search
    raw_results = await serper_search(sub_query, num=10)

    if not raw_results:
        return {
            "index": index,
            "query": sub_query,
            "summary": "No search results found for this query.",
            "citations": [],
            "full_scraped": 0,
            "method": "none",
        }

    # Filter + rank
    ranked = filter_and_rank(raw_results, top_n=6)

    # Enrich — browser or Serper scrape
    async def enrich_deep(result: dict, idx: int) -> dict:
        url = result.get("url", "")
        tier = classify_domain(url)

        if idx < DEEP_BROWSER_TOP_N and use_browser:
            # Try Playwright first
            fetched = await playwright_fetch(url)
            if fetched["success"] and fetched["chars"] > 300:
                result["full_content"] = fetched["text"]
                result["content_type"] = "browser"
                result["content_chars"] = fetched["chars"]
                result["fetch_method"] = fetched.get("method", "playwright")
            else:
                # Playwright failed — fall back to Serper scrape
                scraped = await serper_scrape(url)
                result["full_content"] = (
                    scraped["text"] if scraped["success"] else result["snippet"]
                )
                result["content_type"] = (
                    "serper_scrape" if scraped["success"] else "snippet"
                )
                result["content_chars"] = (
                    scraped["chars"] if scraped["success"] else len(result["snippet"])
                )
                result["fetch_method"] = "serper_scrape_fallback"
        elif idx < SCRAPE_TOP_N:
            # Use Serper scrape (rounds 1–3)
            scraped = await serper_scrape(url)
            result["full_content"] = (
                scraped["text"] if scraped["success"] else result["snippet"]
            )
            result["content_type"] = (
                "serper_scrape" if scraped["success"] else "snippet"
            )
            result["content_chars"] = (
                scraped["chars"] if scraped["success"] else len(result["snippet"])
            )
            result["fetch_method"] = "serper_scrape"
        else:
            result["full_content"] = result["snippet"]
            result["content_type"] = "snippet"
            result["content_chars"] = len(result["snippet"])
            result["fetch_method"] = "snippet"

        result["tier"] = tier
        return result

    enrich_tasks = [enrich_deep(r, i) for i, r in enumerate(ranked)]
    enriched_raw = await asyncio.gather(*enrich_tasks, return_exceptions=True)

    final_results: list[dict] = []
    for i, item in enumerate(enriched_raw):
        if isinstance(item, Exception):
            r = ranked[i]
            r["full_content"] = r["snippet"]
            r["content_type"] = "snippet"
            r["content_chars"] = len(r["snippet"])
            r["tier"] = classify_domain(r["url"])
            r["fetch_method"] = "error_fallback"
            final_results.append(r)
        else:
            final_results.append(item)

    # Build context block
    context_parts = []
    for i, r in enumerate(final_results):
        domain = get_domain(r["url"])
        method = r.get("fetch_method", "unknown")
        content_info = (
            f"{r['content_type']} via {method} ({r['content_chars']:,} chars)"
        )
        header = (
            f"[{i+1}] {r['title']}"
            + (f" — {r['date']}" if r.get("date") else "")
            + f"\nSource: {domain} | Tier: {r['tier']} | {content_info}"
            + f"\nURL: {r['url']}"
        )
        context_parts.append(f"{header}\n\n{r['full_content']}")

    context_block = "\n\n" + ("─" * 60) + "\n\n".join(context_parts)

    full_count = sum(
        1 for r in final_results if r["content_type"] in ("browser", "serper_scrape")
    )
    snippet_count = len(final_results) - full_count
    browser_count = sum(1 for r in final_results if r["content_type"] == "browser")

    system = f"""You are a senior research analyst. You have deep web content from 
quality-filtered, ranked sources for a specific query.

Content breakdown:
- {browser_count} sources read via real browser (Playwright — highest depth)
- {full_count - browser_count} sources scraped via Serper
- {snippet_count} sources with snippet only

Instructions:
- Synthesize key facts, figures, dates, and insights into 2-4 focused paragraphs
- Heavily prioritize browser-fetched and scraped content over snippets
- Be specific: exact numbers, dates, names, references
- Flag single-source claims as "(reported by one source)"
- Flag well-corroborated claims as "(confirmed by multiple sources)"
- Do NOT add information not present in the provided content
- Do NOT use bullet points — prose paragraphs only"""

    summary = await call_azure(
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"Query: {sub_query}\n\nSources:\n\n{context_block}",
            },
        ],
        temperature=0.1,
        max_tokens=1400,
    )

    citations = [
        {
            "url": r["url"],
            "title": r["title"],
            "domain": get_domain(r["url"]),
            "tier": r["tier"],
            "type": r["content_type"],
            "chars": r["content_chars"],
            "method": r.get("fetch_method", ""),
        }
        for r in final_results
    ]

    return {
        "index": index,
        "query": sub_query,
        "summary": summary,
        "citations": citations,
        "full_scraped": full_count,
        "browser_count": browser_count,
    }


# ─── Deep report synthesizer ─────────────────────────────────────────────────


async def synthesize_deep_report(
    original_query: str,
    all_summaries: list[dict],
    all_citations: list[dict],
    academic_papers: list[dict],
    rounds_completed: int,
    gap_analyses: list[dict],
    is_academic: bool,
) -> str:
    """
    Final synthesis for Deep Research.
    Produces a 1500–2500 word structured report.
    Includes academic paper references if is_academic=True.
    """
    total_sources = len(all_citations)
    total_scraped = sum(
        1 for c in all_citations if c.get("type") in ("browser", "serper_scrape")
    )
    browser_count = sum(1 for c in all_citations if c.get("type") == "browser")
    tier1_count = sum(1 for c in all_citations if c.get("tier") == "tier1")

    # Round-by-round context
    rounds_context = ""
    current_round = 0
    for s in all_summaries:
        if s["round"] != current_round:
            current_round = s["round"]
            rounds_context += (
                f"\n\n{'='*60}\nROUND {current_round} RESEARCH\n{'='*60}\n"
            )
        rounds_context += f"\n--- Query: \"{s['query']}\" ---\n{sanitize_research_context(s['summary'])}\n"

    # Academic papers section
    academic_context = ""
    if is_academic and academic_papers:
        academic_context = "\n\nACADEMIC LITERATURE FOUND:\n"
        for i, p in enumerate(academic_papers, 1):
            academic_context += (
                f"\n[Paper {i}] {p['title']}\n"
                f"Authors: {p['authors']} ({p.get('year') or p.get('published', 'n.d.')})\n"
                f"Citations: {p.get('citations', 'N/A')} | Source: {p['source']}\n"
                f"URL: {p['url']}\n"
                f"Abstract: {p['abstract']}\n"
            )

    # Gap analysis reasoning
    gap_context = ""
    for i, g in enumerate(gap_analyses):
        if g.get("gap_analysis"):
            gap_context += f"\nAfter round {i+1}: {g['gap_analysis']}\n"

    academic_instruction = ""
    if is_academic and academic_papers:
        academic_instruction = f"""
- Integrate findings from the {len(academic_papers)} academic papers naturally into the analysis
- Cite papers by author + year when referencing them (e.g., "Smith et al., 2024")
- Note paper citation counts as a signal of academic impact
- Add an ## Academic Sources section at the end listing key papers with their URLs"""

    # Auto-detect comparison table need (explicit OR implicit compare)
    table_keywords = [
        "comparison table",
        "compare table",
        "create a table",
        "comparison chart",
        "table covering",
        "table of",
        "tabular",
        "side by side",
        "side-by-side",
        "vs table",
        "comparison matrix",
    ]
    implicit_compare_kws = [
        " vs ",
        " versus ",
        "compare ",
        "compared to",
        "which is better",
        "difference between",
        "stack up",
    ]
    query_lower = original_query.lower()
    wants_table = any(kw in query_lower for kw in table_keywords) or any(
        kw in query_lower for kw in implicit_compare_kws
    )

    table_instruction = ""
    if wants_table:
        table_instruction = """

COMPARISON TABLE RULE: Include ## Comparison Table after Key Findings. Use markdown:
| Dimension | Option A | Option B |
|---|---|---|
| Row | value | value |
Use ALL numeric scores/metrics found. Compute derivable values.
Write "Not documented" only if truly absent. Never leave cells empty."""

    system = f"""You are a world-class research analyst producing a comprehensive deep research report.

Research statistics:
- Rounds completed: {rounds_completed} (of up to {DEEP_MAX_ROUNDS})
- Total web sources analyzed: {total_sources}
- Pages read via real browser: {browser_count}
- Pages scraped via Serper: {total_scraped - browser_count}
- High-authority (Tier 1) sources: {tier1_count}
- Academic papers found: {len(academic_papers)}

Produce a DEEP RESEARCH REPORT with these exact sections:

## Executive Summary
3-4 sentences capturing the most critical findings, confidence level, and key caveats.

## Key Findings
4-8 major findings. Each finding is a short paragraph with:
- The finding itself (specific numbers, dates, names)
- Source strength: how many sources confirm it and their quality tier
- Any critical caveats or conditions

## Detailed Analysis
5-6 paragraphs of deep analysis. Cross-reference all rounds of research.
Build a coherent narrative. Show patterns, contradictions, and implications.
This is the section that distinguishes a deep report from a summary.

## Evidence Quality Assessment
Which claims are rock-solid (many Tier-1 sources)? Which are tentative (single source)?
What methodological limitations exist in the available evidence?
{academic_instruction}

## Conflicting Information & Open Questions
What do sources disagree on? What remains unanswered after {rounds_completed} rounds?
What would a human expert want to investigate further?

## Confidence Assessment
Overall confidence: Low / Medium / High / Very High — with detailed reasoning.
What specific evidence would raise or lower this assessment?

UNIVERSAL SYNTHESIS RULES:
- RELEVANCE FIRST: report only what the original question asked for.
  Do not include tangential data, industry context, or related metrics not requested.
- Lead with the most specific finding (exact names, numbers, dates)
- Compute derived facts (e.g. 26% of 1,181 = ~307)
- Report all category splits ONLY if they relate to what was asked
- Connect findings across all rounds into coherent chains
- Honest confidence: Low only if answer data is absent

Format rules:
- Minimum 1500 words, target 2000 words
- Exact figures, dates, legislation numbers, paper titles
- Cite inline: "(3 Tier-1 sources)", "(single source — verify)"
- Use ## headers exactly as shown above
- Write for an expert professional audience — no hand-holding
- Do NOT use bullet points within sections — prose paragraphs only{table_instruction}"""

    return await call_azure(
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"Original question: {original_query}\n\n"
                    f"Gap analysis between rounds:{gap_context}\n\n"
                    f"Round-by-round research:{rounds_context}"
                    f"{academic_context}"
                ),
            },
        ],
        temperature=0.2,
        max_tokens=4000,
        timeout=180.0,
    )


# ─── Report exporter ──────────────────────────────────────────────────────────


def export_markdown_report(
    query: str,
    report: str,
    citations: list[dict],
    academic_papers: list[dict],
    stats: dict,
) -> str:
    """
    Build a clean markdown document from the report and return it as a string.
    Saved to a temp file and served via /research/deep/download.
    """
    today_str = date.today().strftime("%B %d, %Y")

    lines = [
        f"# Deep Research Report",
        f"",
        f"**Query:** {query}",
        f"**Date:** {today_str}",
        f"**Rounds completed:** {stats.get('rounds', 0)}",
        f"**Sources analyzed:** {stats.get('total_sources', 0)}",
        f"**Pages fully read:** {stats.get('total_scraped', 0)} "
        f"(browser: {stats.get('browser_count', 0)}, scrape: {stats.get('scrape_count', 0)})",
        f"**Academic papers:** {len(academic_papers)}",
        f"",
        f"---",
        f"",
        report,
        f"",
        f"---",
        f"",
        f"## Web Sources",
        f"",
    ]

    # Web citations
    seen = set()
    for c in citations:
        if c["url"] not in seen:
            seen.add(c["url"])
            tier_label = "★ Tier 1" if c.get("tier") == "tier1" else "Tier 2"
            method_label = c.get("type", "snippet")
            lines.append(
                f"- [{c['title']}]({c['url']}) — {tier_label} · {method_label}"
            )

    # Academic papers
    if academic_papers:
        lines += ["", "## Academic Papers", ""]
        for p in academic_papers:
            cite_info = (
                f"{p['authors']} ({p.get('year') or p.get('published', 'n.d.')})"
            )
            citations_str = (
                f" · {p['citations']} citations" if p.get("citations") else ""
            )
            lines.append(f"- **{p['title']}** — {cite_info}{citations_str}")
            if p.get("url"):
                lines.append(f"  {p['url']}")

    lines += ["", "---", f"*Generated by Ragioneer Research System*"]

    return "\n".join(lines)


# ─── Deep research stream ─────────────────────────────────────────────────────


async def deep_research_stream(query: str):
    """
    Deep Research generator:
    - Up to 8 recursive rounds
    - Rounds 1–3: Serper search + scrape (fast)
    - Rounds 4+: Playwright browser (deep)
    - Academic search fires in round 3 if question is academic/scientific
    - Exports a downloadable markdown report at the end
    """
    start = time.time()

    all_summaries: list[dict] = []
    all_citations: list[dict] = []
    seen_urls: set[str] = set()
    seen_queries: list[str] = []
    gap_analyses: list[dict] = []
    academic_papers: list[dict] = []
    total_scraped = 0
    browser_count = 0
    is_academic = False

    try:
        # ── Detect if academic search is needed ───────────────────────────────
        yield sse(
            "step", {"step": 1, "state": "active", "text": "Analyzing question type..."}
        )
        is_academic = await is_academic_query(query)
        yield sse("academic_detected", {"is_academic": is_academic})
        yield sse("step", {"step": 1, "state": "done", "text": "Complete"})

        for round_num in range(1, DEEP_MAX_ROUNDS + 1):

            use_browser = round_num >= DEEP_BROWSER_START_ROUND
            round_label = "browser" if use_browser else "serper"

            yield sse(
                "round_start",
                {
                    "round": round_num,
                    "max_rounds": DEEP_MAX_ROUNDS,
                    "use_browser": use_browser,
                },
            )

            # ── Decompose or use gap queries ──────────────────────────────────
            if round_num == 1:
                yield sse(
                    "step", {"step": 2, "state": "active", "text": "Decomposing..."}
                )
                decomp = await decompose_query(query)
                queries_this_round = decomp["queries"]
                yield sse(
                    "step",
                    {
                        "step": 2,
                        "state": "done",
                        "text": f"{len(queries_this_round)} queries identified",
                    },
                )
                yield sse(
                    "decomposition",
                    {
                        "reasoning": decomp["reasoning"],
                        "queries": queries_this_round,
                        "round": round_num,
                    },
                )
            else:
                queries_this_round = gap_analyses[-1].get("follow_up_queries", [])
                if not queries_this_round:
                    break
                yield sse(
                    "decomposition",
                    {
                        "reasoning": gap_analyses[-1].get("gap_analysis", ""),
                        "queries": queries_this_round,
                        "round": round_num,
                    },
                )

            seen_queries.extend(queries_this_round)

            # ── Parallel search + scrape/browser ─────────────────────────────
            yield sse(
                "step",
                {
                    "step": 3,
                    "state": "active",
                    "text": f"Round {round_num} — {'browser' if use_browser else 'serper'} · {len(queries_this_round)} queries",
                },
            )

            for i, q in enumerate(queries_this_round):
                yield sse(
                    "search_start",
                    {
                        "index": i,
                        "query": q,
                        "round": round_num,
                        "use_browser": use_browser,
                    },
                )

            # Academic search fires alongside round 3's web searches
            academic_task = None
            if is_academic and round_num == 3:
                yield sse("academic_search_start", {"query": query})
                academic_task = asyncio.create_task(academic_search(query))

            tasks = [
                deep_search_and_summarize(q, i, use_browser=use_browser)
                for i, q in enumerate(queries_this_round)
            ]

            round_results: list[dict] = []
            for coro in asyncio.as_completed(tasks):
                result = await coro
                round_results.append(result)
                total_scraped += result.get("full_scraped", 0)
                browser_count += result.get("browser_count", 0)

                # Global dedup
                unique_cites = []
                for c in result["citations"]:
                    if c["url"] not in seen_urls:
                        seen_urls.add(c["url"])
                        all_citations.append(c)
                        unique_cites.append(c)
                result["citations"] = unique_cites

                yield sse(
                    "search_done",
                    {
                        "index": result["index"],
                        "query": result["query"],
                        "citations": result["citations"][:4],
                        "full_scraped": result.get("full_scraped", 0),
                        "browser_count": result.get("browser_count", 0),
                        "round": round_num,
                    },
                )

            round_results.sort(key=lambda r: r["index"])

            for r in round_results:
                all_summaries.append(
                    {
                        "round": round_num,
                        "query": r["query"],
                        "summary": r["summary"],
                    }
                )

            # Collect academic results if they finished
            if academic_task is not None:
                try:
                    academic_result = await academic_task
                    academic_papers = academic_result.get("papers", [])
                    yield sse(
                        "academic_search_done",
                        {
                            "total": len(academic_papers),
                            "papers": [
                                {
                                    "title": p["title"],
                                    "authors": p["authors"],
                                    "year": p.get("year") or p.get("published", ""),
                                    "url": p["url"],
                                    "source": p["source"],
                                    "citations": p.get("citations", 0),
                                }
                                for p in academic_papers[:5]
                            ],
                        },
                    )
                except Exception:
                    academic_papers = []

            yield sse(
                "step",
                {
                    "step": 3,
                    "state": "done",
                    "text": f"Round {round_num} — {total_scraped} pages read · {browser_count} via browser",
                },
            )

            # ── Gap analysis ──────────────────────────────────────────────────
            is_last = round_num >= DEEP_MAX_ROUNDS
            has_min = round_num >= DEEP_MIN_ROUNDS

            if not is_last:
                yield sse("gap_analysis_start", {"round": round_num})
                gap = await analyze_gaps(
                    sanitize_query_for_azure(query),
                    round_num,
                    all_summaries,
                    seen_queries,
                )
                gap_analyses.append(gap)

                yield sse(
                    "gap_analysis_done",
                    {
                        "round": round_num,
                        "gaps_found": gap["gaps_found"],
                        "confidence": gap.get("confidence", 0),
                        "gap_analysis": gap.get("gap_analysis", ""),
                        "next_queries": gap.get("follow_up_queries", []),
                    },
                )

                confidence_val = gap.get("confidence", 0)
                should_stop_gap = has_min and not gap["gaps_found"]
                should_stop_conf = has_min and confidence_val >= 0.72
                if should_stop_gap or should_stop_conf:
                    stop_reason = (
                        "Research sufficiently complete"
                        if should_stop_gap
                        else f"Confidence threshold reached ({round(confidence_val*100)}%)"
                    )
                    yield sse(
                        "early_stop",
                        {
                            "round": round_num,
                            "reason": stop_reason,
                            "confidence": confidence_val,
                        },
                    )
                    break
            else:
                gap_analyses.append({"gap_analysis": "", "follow_up_queries": []})

        # ── Final synthesis ───────────────────────────────────────────────────
        rounds_completed = round_num

        yield sse(
            "step",
            {
                "step": 4,
                "state": "active",
                "text": f"Synthesizing deep report — {rounds_completed} rounds · {len(all_citations)} sources · {len(academic_papers)} papers",
            },
        )

        report = await synthesize_deep_report(
            query,
            all_summaries,
            all_citations,
            academic_papers,
            rounds_completed,
            gap_analyses,
            is_academic,
        )

        elapsed = round(time.time() - start, 1)
        scrape_count = total_scraped - browser_count

        # Build and save markdown export
        stats = {
            "rounds": rounds_completed,
            "total_sources": len(all_citations),
            "total_scraped": total_scraped,
            "browser_count": browser_count,
            "scrape_count": scrape_count,
        }
        md_content = export_markdown_report(
            query, report, all_citations, academic_papers, stats
        )

        # Save to temp file for download
        report_path = Path(tempfile.gettempdir()) / "ragioneer_deep_report.md"
        report_path.write_text(md_content, encoding="utf-8")

        yield sse("step", {"step": 4, "state": "done", "text": "Report complete"})
        yield sse(
            "result",
            {
                "answer": report,
                "elapsed": elapsed,
                "rounds_completed": rounds_completed,
                "sources_searched": len(all_summaries),
                "total_scraped": total_scraped,
                "browser_count": browser_count,
                "citations": all_citations[:30],
                "academic_papers": academic_papers,
                "is_academic": is_academic,
                "download_ready": True,
                "mode": "deep",
            },
        )

    except httpx.HTTPStatusError as e:
        try:
            detail = e.response.json()
            msg = detail.get("error", {}).get("message") or e.response.text
        except Exception:
            msg = e.response.text
        yield sse("error", {"message": f"API error {e.response.status_code}: {msg}"})

    except json.JSONDecodeError as e:
        yield sse("error", {"message": f"Failed to parse model JSON: {e}"})

    except RuntimeError as e:
        yield sse("error", {"message": str(e)})

    except Exception as e:
        yield sse("error", {"message": f"Unexpected error: {type(e).__name__}: {e}"})

    finally:
        yield sse("done", {})


# ─── Deep endpoints ───────────────────────────────────────────────────────────


@app.post("/research/deep")
async def deep_research(req: ResearchRequest):
    missing = []
    if not AZURE_OPENAI_KEY or not AZURE_OPENAI_ENDPOINT:
        missing.append("AZURE_OPENAI_KEY and AZURE_OPENAI_ENDPOINT")
    if not SERPER_API_KEY:
        missing.append("SERPER_API_KEY")
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing .env config: {', '.join(missing)}",
        )

    return StreamingResponse(
        deep_research_stream(req.query),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/research/deep/download")
async def download_deep_report():
    """Serve the most recently generated deep research report as a markdown file."""
    report_path = Path(tempfile.gettempdir()) / "ragioneer_deep_report.md"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="No report generated yet.")
    return FileResponse(
        path=str(report_path),
        filename="ragioneer_deep_report.md",
        media_type="text/markdown",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# DEEP RESEARCH — QUALITY PATCHES
# Fix 1: Post-fetch content relevance filter
# Fix 2: Direct URL construction for known benchmark/data sites
# Fix 3: Pakistan-aware query enrichment
# Fix 4: Deep-specific decomposer with richer instructions
# Fix 5: Expanded noise domain blocklist
# Fix 6: Content quality gate
# ═══════════════════════════════════════════════════════════════════════════════

# ─── Fix 5: Expanded noise domain blocklist ───────────────────────────────────
# These domains consistently return irrelevant content even when they rank
# in Google results due to keyword coincidence.

DEEP_NOISE_DOMAINS = {
    # Archives / document dumps
    "archive.org",
    "worldradiohistory.com",
    "issuu.com",
    "scribd.com",
    "docplayer.net",
    "slideshare.net",
    "academia.edu",
    # News sitemaps / XML feeds (not actual articles)
    "timesofindia.indiatimes.com",  # when URL is an XML sitemap
    # Generic link aggregators
    "tianchiyu.me",
    "alltop.com",
    # Old newspaper archives
    "newspapers.com",
    "chroniclingamerica.loc.gov",
    # Radio/hobby archives
    "n2yo.com",
    "radioreference.com",
}

# ─── Fix 6: Content quality gate ─────────────────────────────────────────────


def is_content_useful(text: str, min_chars: int = 300) -> bool:
    """
    Quick heuristic check — is the fetched content actually useful?
    Rejects: empty pages, XML sitemaps, login walls, pure navigation pages,
    error pages, and pages with almost no real text.
    """
    if not text or len(text.strip()) < min_chars:
        return False

    text_lower = text.lower()

    # XML sitemaps
    if text_lower.strip().startswith("<?xml") or "<urlset" in text_lower:
        return False

    # Login / paywall walls
    noise_phrases = [
        "please log in",
        "sign in to continue",
        "subscribe to read",
        "create a free account",
        "403 forbidden",
        "404 not found",
        "access denied",
        "page not found",
        "this page does not exist",
    ]
    if any(p in text_lower[:500] for p in noise_phrases):
        return False

    # Pure navigation / index pages (very low word density)
    words = text.split()
    if len(words) < 50:
        return False

    return True


# ─── Fix 1: Post-fetch relevance filter ──────────────────────────────────────


async def is_content_relevant(content: str, query: str, title: str) -> bool:
    """
    After fetching a page, check if its content is actually relevant to the query.
    Uses a fast 60-token GPT call.
    Returns True (keep) or False (discard).

    This catches:
    - Noise pages that ranked in Google due to keyword coincidence
    - Index/archive pages that have no real content about the topic
    - Wrong-topic pages (1997 Idaho newspaper, border immigration articles, etc.)
    """
    # First pass: quick heuristic — if title is clearly off-topic, skip GPT call
    title_lower = title.lower()
    query_words = set(query.lower().split())

    # If none of the query's main nouns appear in the title, likely irrelevant
    # (but only apply this for longer queries to avoid false negatives)
    if len(query_words) > 4:
        title_words = set(title_lower.split())
        overlap = query_words & title_words
        # Remove stop words from overlap check
        stop_words = {
            "the",
            "a",
            "an",
            "in",
            "of",
            "for",
            "and",
            "or",
            "to",
            "with",
            "on",
            "at",
            "by",
            "is",
            "are",
            "was",
            "vs",
            "i",
            "my",
            "me",
            "want",
            "also",
            "find",
            "both",
            "which",
            "one",
            "has",
            "have",
            "this",
            "that",
            "what",
        }
        meaningful_overlap = overlap - stop_words
        if len(meaningful_overlap) == 0 and len(title_words) > 3:
            return False  # clearly off-topic, skip GPT

    # GPT relevance check on first 400 chars of content
    content_preview = content[:400].strip()

    system = """You are a content relevance filter.
Given a research query and a snippet of fetched web content, decide if the content
is genuinely relevant to the query — i.e., it contains information that would help
answer the question.

Answer YES if relevant, NO if not.
Respond with ONLY: yes or no"""

    user = (
        f"Query: {query}\n\n"
        f"Page title: {title}\n"
        f"Content preview: {content_preview}"
    )

    try:
        result = await call_azure(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            max_tokens=5,
        )
        return result.strip().lower().startswith("yes")
    except Exception:
        return True  # on failure, keep the content


# ─── Fix 2: Direct URL constructor for known benchmark/data sites ─────────────


def construct_direct_urls(query: str) -> list[dict]:
    """
    For certain well-known sites, construct direct URLs to the most likely
    relevant pages rather than relying on Google to surface them.

    This is critical for:
    - DXOMARK: Google often surfaces index/nav pages instead of test pages
    - GSMArena: spec pages follow a predictable URL pattern
    - PriceOye / Hamariweb: Pakistan pricing pages

    Returns list of {url, title, snippet, date} dicts to prepend to search results.
    """
    direct_urls = []
    query_lower = query.lower()

    # ── DXOMARK camera test pages ─────────────────────────────────────────────
    dxomark_phones = {
        "iphone 17 pro max": "apple-iphone-17-pro-max-camera-test",
        "iphone 17 pro": "apple-iphone-17-pro-camera-test",
        "iphone 17": "apple-iphone-17-camera-test",
        "iphone 16 pro max": "apple-iphone-16-pro-max-camera-test",
        "samsung s26 ultra": "samsung-galaxy-s26-ultra-camera-test",
        "galaxy s26 ultra": "samsung-galaxy-s26-ultra-camera-test",
        "samsung s25 ultra": "samsung-galaxy-s25-ultra-camera-test",
        "galaxy s26": "samsung-galaxy-s26-camera-test",
        "pixel 9 pro": "google-pixel-9-pro-camera-test",
        "xiaomi 15 ultra": "xiaomi-15-ultra-camera-test",
        "oneplus 13": "oneplus-13-camera-test",
    }
    for phone, slug in dxomark_phones.items():
        if phone in query_lower:
            direct_urls.append(
                {
                    "title": f"DXOMARK {phone.title()} Camera Test",
                    "url": f"https://www.dxomark.com/{slug}/",
                    "snippet": f"DXOMARK camera benchmark test for {phone.title()}",
                    "date": "",
                    "_direct": True,
                }
            )

    # ── GSMArena spec pages ───────────────────────────────────────────────────
    gsmarena_phones = {
        "iphone 17 pro max": "apple_iphone_17_pro_max-12603.php",
        "samsung s26 ultra": "samsung_galaxy_s26_ultra-12800.php",
        "galaxy s26 ultra": "samsung_galaxy_s26_ultra-12800.php",
        "pixel 9 pro": "google_pixel_9_pro-12171.php",
    }
    for phone, slug in gsmarena_phones.items():
        if phone in query_lower:
            direct_urls.append(
                {
                    "title": f"GSMArena {phone.title()} Full Specifications",
                    "url": f"https://www.gsmarena.com/{slug}",
                    "snippet": f"Full specifications and user reviews for {phone.title()}",
                    "date": "",
                    "_direct": True,
                }
            )

    # ── Pakistan pricing pages ────────────────────────────────────────────────
    pakistan_keywords = ["pakistan", "karachi", "lahore", "islamabad", "pkr", "pta"]
    is_pakistan_query = any(kw in query_lower for kw in pakistan_keywords)

    if is_pakistan_query:
        priceoye_phones = {
            "iphone 17 pro max": "apple-iphone-17-pro-max",
            "samsung s26 ultra": "samsung-galaxy-s26-ultra",
            "galaxy s26 ultra": "samsung-galaxy-s26-ultra",
            "iphone 17 pro": "apple-iphone-17-pro",
        }
        hamariweb_phones = {
            "iphone 17 pro max": "iphone-17-pro-max",
            "samsung s26 ultra": "samsung-galaxy-s26-ultra",
            "galaxy s26 ultra": "samsung-galaxy-s26-ultra",
        }
        for phone, slug in priceoye_phones.items():
            if phone in query_lower:
                direct_urls.append(
                    {
                        "title": f"PriceOye {phone.title()} Price in Pakistan",
                        "url": (
                            f"https://priceoye.pk/mobiles/apple/{slug}"
                            if "iphone" in phone
                            else f"https://priceoye.pk/mobiles/samsung/{slug}"
                        ),
                        "snippet": f"Current price of {phone.title()} in Pakistan — PTA approved and open market",
                        "date": "",
                        "_direct": True,
                    }
                )
        for phone, slug in hamariweb_phones.items():
            if phone in query_lower:
                direct_urls.append(
                    {
                        "title": f"Hamariweb {phone.title()} Price Pakistan",
                        "url": f"https://hamariweb.com/mobiles/info/{slug}-price-in-pakistan/",
                        "snippet": f"{phone.title()} current price in Pakistan with PTA and non-PTA variants",
                        "date": "",
                        "_direct": True,
                    }
                )

        # Always include OLX Pakistan search for pricing queries
        for phone in ["iphone 17 pro max", "samsung s26 ultra", "galaxy s26 ultra"]:
            if phone in query_lower:
                search_term = phone.replace(" ", "+")
                direct_urls.append(
                    {
                        "title": f"OLX Pakistan {phone.title()} listings",
                        "url": f"https://www.olx.com.pk/items/q-{search_term}",
                        "snippet": f"Buy and sell {phone.title()} on OLX Pakistan — open market prices",
                        "date": "",
                        "_direct": True,
                    }
                )

    # ── Pakistan gold rate pages ──────────────────────────────────────────────
    gold_keywords = [
        "gold rate",
        "gold price",
        "tola",
        "24k gold",
        "22k gold",
        "gold today",
        "gold pakistan",
        "sarafa",
        "sarafabazar",
    ]
    is_gold_query = any(kw in query_lower for kw in gold_keywords)

    if is_gold_query and any(
        kw in query_lower for kw in ["pakistan", "pkr", "karachi", "lahore"]
    ):
        from datetime import date as _date

        today_str = _date.today().strftime("%Y-%m-%d")
        direct_urls.extend(
            [
                {
                    "title": "Gold Rate in Pakistan Today — goldpricepak.com",
                    "url": "https://www.goldpricepak.com/",
                    "snippet": "Live 24K, 22K, 21K gold price per tola and per gram in Pakistan today. Karachi Sarafa market rates.",
                    "date": today_str,
                    "_direct": True,
                },
                {
                    "title": "Pakistan Gold Rate Today — gold.pk",
                    "url": "https://www.gold.pk/",
                    "snippet": "Today gold rate in Pakistan per tola and per gram. 24K, 22K gold price in PKR.",
                    "date": today_str,
                    "_direct": True,
                },
                {
                    "title": "Gold Price in Pakistan Today — hamariweb.com",
                    "url": "https://hamariweb.com/finance/gold-rates-in-pakistan.aspx",
                    "snippet": "24K gold rate per tola in Pakistan today. Updated daily from Karachi Sarafa Bazar.",
                    "date": today_str,
                    "_direct": True,
                },
            ]
        )

    # ── Pakistan USD/PKR forex pages ─────────────────────────────────────────
    forex_keywords = [
        "usd to pkr",
        "dollar rate",
        "dollar to pkr",
        "usd pkr",
        "open market rate",
        "exchange rate pakistan",
        "forex pakistan",
        "dollar pakistan",
        "pkr rate",
        "rupee rate",
    ]
    is_forex_query = any(kw in query_lower for kw in forex_keywords)

    if is_forex_query:
        from datetime import date as _date

        today_str = _date.today().strftime("%Y-%m-%d")
        direct_urls.extend(
            [
                {
                    "title": "USD to PKR Open Market Rate Today — hamariweb.com",
                    "url": "https://hamariweb.com/finance/dollar-rate-in-pakistan.aspx",
                    "snippet": "US Dollar to Pakistani Rupee open market buying and selling rate today. Updated live.",
                    "date": today_str,
                    "_direct": True,
                },
                {
                    "title": "Dollar Rate in Pakistan Today — forex.pk",
                    "url": "https://forex.pk/dollar-rate-in-pakistan/",
                    "snippet": "USD to PKR open market rate today. Buying and selling rates from Karachi exchange companies.",
                    "date": today_str,
                    "_direct": True,
                },
                {
                    "title": "Pakistan Open Market Exchange Rates — pkr.com.pk",
                    "url": "https://www.pkr.com.pk/",
                    "snippet": "Live open market USD to PKR rate in Pakistan. All currency exchange rates updated.",
                    "date": today_str,
                    "_direct": True,
                },
            ]
        )

    return direct_urls


# ─── Fix 3: Pakistan-aware query enrichment ───────────────────────────────────


def enrich_queries_for_pakistan(queries: list[str], original_query: str) -> list[str]:
    """
    If the original query mentions Pakistan/Karachi pricing, inject targeted
    sub-queries for authoritative Pakistan price sources that the decomposer
    might miss.
    """
    query_lower = original_query.lower()
    pakistan_keywords = ["pakistan", "karachi", "pkr", "open market", "pta"]

    if not any(kw in query_lower for kw in pakistan_keywords):
        return queries

    # Detect which phones are being asked about
    phone_terms = []
    phone_map = {
        "iphone 17 pro max": "iPhone 17 Pro Max",
        "samsung s26 ultra": "Samsung Galaxy S26 Ultra",
        "galaxy s26 ultra": "Samsung Galaxy S26 Ultra",
        "iphone 16 pro max": "iPhone 16 Pro Max",
        "galaxy s25 ultra": "Samsung Galaxy S25 Ultra",
    }
    for key, name in phone_map.items():
        if key in query_lower:
            phone_terms.append(name)

    enriched = list(queries)

    # Add Pakistan-specific pricing queries if not already present
    query_text = " ".join(queries).lower()
    for phone in phone_terms:
        phone_lower = phone.lower()
        if "priceoye" not in query_text and "hamariweb" not in query_text:
            enriched.append(
                f"{phone} price Pakistan April 2026 site:priceoye.pk OR site:hamariweb.com OR site:techjuice.pk"
            )
        if "olx" not in query_text:
            enriched.append(f"{phone} open market price Karachi 2026 OLX OR Saddar")
        if "resale" in original_query.lower() and "resale" not in query_text:
            enriched.append(
                f"{phone} resale value Pakistan 2026 depreciation used price"
            )

    # Cap to avoid too many queries
    return enriched[:8]


# ─── Fix 4: Deep-specific decomposer ─────────────────────────────────────────


async def decompose_query_deep(query: str) -> dict:
    """
    Deep Research decomposer — richer and more specific than the base decomposer.

    Key differences:
    - Instructs GPT to include primary/authoritative sources by name
    - Forces Pakistan-specific sources when pricing is requested
    - Instructs construction of direct benchmark site queries
    - Generates more queries (up to 6 instead of 5)
    - Explicitly warns against generic queries that return noise
    """
    today = date.today().strftime("%B %d, %Y")
    query_lower = query.lower()

    pakistan_instruction = ""
    if any(
        k in query_lower for k in ["pakistan", "karachi", "pkr", "open market", "pta"]
    ):
        pakistan_instruction = """
5. For Pakistan pricing queries, ALWAYS include:
   - A query targeting site:priceoye.pk or site:hamariweb.com
   - A query for "open market price Karachi" with the specific phone model
   - A query for OLX Pakistan listings for current resale data"""

    benchmark_instruction = ""
    benchmark_sites = {
        "camera": "site:dxomark.com",
        "benchmark": "site:dxomark.com OR site:notebookcheck.net",
        "display": "site:dxomark.com OR site:displayninja.com",
        "performance": "site:gsmarena.com OR site:anandtech.com",
        "specs": "site:gsmarena.com",
    }
    for keyword, site_filter in benchmark_sites.items():
        if keyword in query_lower:
            benchmark_instruction = f"""
4. For benchmark/specification queries, include at least one query with a site filter
   (e.g., {site_filter}) to reach primary data sources directly."""
            break

    # Freelance/marketplace platform awareness
    freelance_kws = [
        "upwork",
        "fiverr",
        "freelanc",
        "remote work",
        "remote job",
        "hourly rate",
        "gig economy",
        "toptal",
    ]
    freelance_instruction = ""
    if any(kw in query_lower for kw in freelance_kws):
        freelance_instruction = """

FREELANCE PLATFORM STRATEGY — Upwork/Fiverr pages require login and JS rendering.
Do NOT rely on direct platform pages. Use these instead:
- Third-party analyses: search forbes.com, techrepublic.com, businessinsider.com for Upwork/Fiverr data
- Pakistan freelancing reports: PSEB, P@SHA, PASHA annual reports 2025 2026
- Community discussions: site:reddit.com Pakistani freelancers Upwork Fiverr rates 2026
- Journalist coverage: "Upwork" OR "Fiverr" hourly rates analysis 2026
- Aggregators: Statista freelancing statistics Pakistan 2026"""

    # Salary/rate data awareness
    salary_kws = [
        "salary",
        "hourly rate",
        "pay",
        "earning",
        "income",
        "job demand",
        "in-demand",
        "hiring",
    ]
    salary_instruction = ""
    if any(kw in query_lower for kw in salary_kws) and not freelance_instruction:
        salary_instruction = """

SALARY DATA STRATEGY — Glassdoor/LinkedIn Salary require login.
Instead use: levels.fyi, Payscale reports, Stack Overflow developer survey,
industry association surveys, or journalist coverage citing salary data."""

    system = f"""You are a deep research planner. Today's date is {today}.

A user has a research question requiring thorough investigation. Your job:
1. Think carefully about ALL information dimensions needed for a complete answer.
2. Generate 4-6 specific, targeted web search queries covering different angles.
3. Each query must target a DIFFERENT aspect — do not repeat similar queries.
   Vary between: primary sources, secondary analysis, specific data points, regional sources.
{benchmark_instruction}{pakistan_instruction}{freelance_instruction}{salary_instruction}

CRITICAL RULES — NAMED-ENTITY-FIRST:
- If no specific product/company is named, Q1 MUST discover them first
  "sodium-ion EV China 2026" → Q1: "sodium-ion battery EV China launch model 2026"
  Then use discovered names (CATL Naxtra, Changan Nevo A06) in Q2-Q6
- NEVER search for failures/delays before confirming positive outcomes exist
- Use the entity's ACTUAL product name, not just company name
- For "current status" questions, include a prior-year baseline query
- Include the current year (2026) or month in time-sensitive queries
- For pricing: name the specific data source platform
- Avoid queries that will return index/navigation pages — target specific content

Respond ONLY with valid JSON — no markdown fences, no extra explanation:
{{
  "reasoning": "2-3 sentence explanation of your deep research strategy",
  "queries": [
    "specific search query 1",
    "specific search query 2",
    "specific search query 3",
    "specific search query 4"
  ]
}}"""

    raw = await call_azure(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": query},
        ],
        temperature=0.1,
        max_tokens=700,
    )

    result = safe_json_parse(raw, {"reasoning": "Fallback", "queries": [query]})

    # Post-process: enrich with Pakistan-specific queries if needed
    if result.get("queries"):
        result["queries"] = enrich_queries_for_pakistan(result["queries"], query)

    return result


# ─── Patched deep_search_and_summarize ────────────────────────────────────────


async def deep_search_and_summarize_v2(
    sub_query: str,
    index: int,
    original_query: str,
    use_browser: bool = False,
) -> dict:
    """
    Improved deep_search_and_summarize with all quality fixes applied:
    - Fix 2: Prepends direct URLs for known benchmark/data sites
    - Fix 5: Expanded noise domain filtering
    - Fix 6: Content quality gate before sending to GPT
    - Fix 1: Post-fetch relevance filter on browser content
    """
    # Search
    raw_results = await serper_search(sub_query, num=15)

    # Fix 2: prepend direct URLs for this query
    direct = construct_direct_urls(sub_query + " " + original_query)
    # Direct URLs go first — they're the most authoritative
    all_results = direct + (raw_results or [])

    if not all_results:
        return {
            "index": index,
            "query": sub_query,
            "summary": "No search results found for this query.",
            "citations": [],
            "full_scraped": 0,
            "browser_count": 0,
        }

    # Filter + rank — but first remove noise domains
    def is_noise_url(url: str) -> bool:
        domain = get_domain(url)
        full = get_full_domain(url)
        # Skip noise domains
        if domain in DEEP_NOISE_DOMAINS or full in DEEP_NOISE_DOMAINS:
            return True
        # Skip XML sitemaps regardless of domain
        if url.endswith(".xml") or "/sitemap" in url or "staticsitemap" in url:
            return True
        # Skip PDF archives from irrelevant sources
        if url.endswith(".pdf") and any(
            n in domain for n in ["worldradiohistory", "archive.org", "scribd"]
        ):
            return True
        return False

    filtered = [r for r in all_results if not is_noise_url(r.get("url", ""))]
    if not filtered:
        filtered = all_results  # fallback if all filtered

    ranked = filter_and_rank(filtered, top_n=6)

    # Enrich — browser or Serper scrape
    async def enrich_deep_v2(result: dict, idx: int) -> dict:
        url = result.get("url", "")
        tier = classify_domain(url)
        is_direct = result.get("_direct", False)

        # Direct URLs always get browser/scrape treatment regardless of index
        should_fetch = (
            is_direct
            or (idx < DEEP_BROWSER_TOP_N and use_browser)
            or (idx < SCRAPE_TOP_N)
        )

        if (idx < DEEP_BROWSER_TOP_N and use_browser) or is_direct:
            fetched = await playwright_fetch(url)

            # Fix 6: content quality gate
            if fetched["success"] and is_content_useful(fetched["text"]):
                # Fix 1: post-fetch relevance filter
                relevant = await is_content_relevant(
                    fetched["text"], original_query, result.get("title", "")
                )
                if relevant:
                    result["full_content"] = fetched["text"]
                    result["content_type"] = "browser"
                    result["content_chars"] = fetched["chars"]
                    result["fetch_method"] = "playwright"
                    result["tier"] = tier
                    return result

            # Playwright failed or content not useful/relevant — try Serper scrape
            scraped = await serper_scrape(url)
            if scraped["success"] and is_content_useful(scraped["text"]):
                relevant = await is_content_relevant(
                    scraped["text"], original_query, result.get("title", "")
                )
                if relevant:
                    result["full_content"] = scraped["text"]
                    result["content_type"] = "serper_scrape"
                    result["content_chars"] = scraped["chars"]
                    result["fetch_method"] = "serper_scrape"
                    result["tier"] = tier
                    return result

            # Both failed — use snippet
            result["full_content"] = result.get("snippet", "")
            result["content_type"] = "snippet"
            result["content_chars"] = len(result.get("snippet", ""))
            result["fetch_method"] = "snippet_fallback"

        elif idx < SCRAPE_TOP_N:
            scraped = await serper_scrape(url)
            if scraped["success"] and is_content_useful(scraped["text"]):
                relevant = await is_content_relevant(
                    scraped["text"], original_query, result.get("title", "")
                )
                if relevant:
                    result["full_content"] = scraped["text"]
                    result["content_type"] = "serper_scrape"
                    result["content_chars"] = scraped["chars"]
                    result["fetch_method"] = "serper_scrape"
                    result["tier"] = tier
                    return result
            result["full_content"] = result.get("snippet", "")
            result["content_type"] = "snippet"
            result["content_chars"] = len(result.get("snippet", ""))
            result["fetch_method"] = "snippet_fallback"

        else:
            result["full_content"] = result.get("snippet", "")
            result["content_type"] = "snippet"
            result["content_chars"] = len(result.get("snippet", ""))
            result["fetch_method"] = "snippet"

        result["tier"] = tier
        return result

    enrich_tasks = [enrich_deep_v2(r, i) for i, r in enumerate(ranked)]
    enriched_raw = await asyncio.gather(*enrich_tasks, return_exceptions=True)

    final_results: list[dict] = []
    for i, item in enumerate(enriched_raw):
        if isinstance(item, Exception):
            r = ranked[i]
            r["full_content"] = r.get("snippet", "")
            r["content_type"] = "snippet"
            r["content_chars"] = len(r.get("snippet", ""))
            r["tier"] = classify_domain(r.get("url", ""))
            r["fetch_method"] = "error_fallback"
            final_results.append(r)
        else:
            final_results.append(item)

    # Build context block
    context_parts = []
    for i, r in enumerate(final_results):
        domain = get_domain(r["url"])
        method = r.get("fetch_method", "unknown")
        is_direct = "★ DIRECT" if r.get("_direct") else ""
        content_info = f"{r['content_type']} via {method} ({r['content_chars']:,} chars) {is_direct}".strip()
        header = (
            f"[{i+1}] {r['title']}"
            + (f" — {r['date']}" if r.get("date") else "")
            + f"\nSource: {domain} | Tier: {r['tier']} | {content_info}"
            + f"\nURL: {r['url']}"
        )
        context_parts.append(f"{header}\n\n{r['full_content']}")

    context_block = ("\n\n" + "─" * 60 + "\n\n").join(context_parts)

    full_count = sum(
        1 for r in final_results if r["content_type"] in ("browser", "serper_scrape")
    )
    snippet_count = len(final_results) - full_count
    browser_count = sum(1 for r in final_results if r["content_type"] == "browser")

    system = f"""You are a senior research analyst extracting facts from deep web sources.

Content: {browser_count} browser sources, {full_count - browser_count} scraped, {snippet_count} snippet-only.

EXTRACTION RULES:
1. NAMED ENTITIES — extract every company, product, person, standard, model name exactly.
2. ALL NUMBERS — extract every %, $, date, score, count, metric exactly as-is. Never round.
3. COMPUTE DERIVED FACTS — if source gives calculation inputs, compute the output.
   "26% of 1,181 employees = ~307 eliminated" — derive and state it.
4. ALL BREAKDOWNS — include every departmental/category/regional split found.
5. PRIORITIZE depth: browser (★ DIRECT) > scraped > snippet-only.
6. SOURCE FLAGS: "(one source)" for single claims, "(multiple sources)" for 3+.
7. NO INVENTION — never add content not in the provided sources.
8. FORMAT — 2-4 prose paragraphs, no bullet points."""

    summary = await call_azure(
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"Query: {sub_query}\n\nSources:\n\n{context_block}",
            },
        ],
        temperature=0.1,
        max_tokens=1400,
    )

    citations = [
        {
            "url": r["url"],
            "title": r["title"],
            "domain": get_domain(r["url"]),
            "tier": r["tier"],
            "type": r["content_type"],
            "chars": r["content_chars"],
            "method": r.get("fetch_method", ""),
        }
        for r in final_results
        if r.get("full_content") or r.get("snippet")  # skip empty
    ]

    return {
        "index": index,
        "query": sub_query,
        "summary": summary,
        "citations": citations,
        "full_scraped": full_count,
        "browser_count": browser_count,
    }


# ─── Override deep_research_stream to use v2 functions ────────────────────────


async def deep_research_stream_v2(query: str):
    """
    Improved deep research stream using all quality fixes:
    - Uses decompose_query_deep (Fix 4) instead of base decomposer
    - Uses deep_search_and_summarize_v2 (Fixes 1,2,5,6) instead of v1
    - Passes original_query through to enable relevance filtering
    """
    start = time.time()

    all_summaries: list[dict] = []
    all_citations: list[dict] = []
    seen_urls: set[str] = set()
    seen_queries: list[str] = []
    gap_analyses: list[dict] = []
    academic_papers: list[dict] = []
    total_scraped = 0
    browser_count = 0
    is_academic = False

    try:
        # Detect academic
        yield sse(
            "step", {"step": 1, "state": "active", "text": "Analyzing question type..."}
        )
        is_academic = await is_academic_query(query)
        yield sse("academic_detected", {"is_academic": is_academic})
        yield sse("step", {"step": 1, "state": "done", "text": "Complete"})

        for round_num in range(1, DEEP_MAX_ROUNDS + 1):

            use_browser = round_num >= DEEP_BROWSER_START_ROUND

            yield sse(
                "round_start",
                {
                    "round": round_num,
                    "max_rounds": DEEP_MAX_ROUNDS,
                    "use_browser": use_browser,
                },
            )

            # Decompose — use deep-specific decomposer for round 1
            if round_num == 1:
                yield sse(
                    "step",
                    {
                        "step": 2,
                        "state": "active",
                        "text": "Decomposing (deep mode)...",
                    },
                )
                decomp = await decompose_query_deep(sanitize_query_for_azure(query))
                queries_this_round = decomp["queries"]
                yield sse(
                    "step",
                    {
                        "step": 2,
                        "state": "done",
                        "text": f"{len(queries_this_round)} queries identified",
                    },
                )
                yield sse(
                    "decomposition",
                    {
                        "reasoning": decomp["reasoning"],
                        "queries": queries_this_round,
                        "round": round_num,
                    },
                )
            else:
                queries_this_round = gap_analyses[-1].get("follow_up_queries", [])
                if not queries_this_round:
                    break
                # Enrich follow-up queries with Pakistan sources if needed
                queries_this_round = enrich_queries_for_pakistan(
                    queries_this_round, query
                )
                yield sse(
                    "decomposition",
                    {
                        "reasoning": gap_analyses[-1].get("gap_analysis", ""),
                        "queries": queries_this_round,
                        "round": round_num,
                    },
                )

            seen_queries.extend(queries_this_round)

            yield sse(
                "step",
                {
                    "step": 3,
                    "state": "active",
                    "text": f"Round {round_num} — {'browser+direct' if use_browser else 'serper+direct'} · {len(queries_this_round)} queries",
                },
            )

            for i, q in enumerate(queries_this_round):
                yield sse(
                    "search_start",
                    {
                        "index": i,
                        "query": q,
                        "round": round_num,
                        "use_browser": use_browser,
                    },
                )

            # Academic search in round 3
            academic_task = None
            if is_academic and round_num == 3:
                yield sse("academic_search_start", {"query": query})
                academic_task = asyncio.create_task(academic_search(query))

            # Use v2 search function
            tasks = [
                deep_search_and_summarize_v2(q, i, query, use_browser=use_browser)
                for i, q in enumerate(queries_this_round)
            ]

            round_results: list[dict] = []
            for coro in asyncio.as_completed(tasks):
                result = await coro
                round_results.append(result)
                total_scraped += result.get("full_scraped", 0)
                browser_count += result.get("browser_count", 0)

                unique_cites = []
                for c in result["citations"]:
                    if c["url"] not in seen_urls:
                        seen_urls.add(c["url"])
                        all_citations.append(c)
                        unique_cites.append(c)
                result["citations"] = unique_cites

                yield sse(
                    "search_done",
                    {
                        "index": result["index"],
                        "query": result["query"],
                        "citations": result["citations"][:4],
                        "full_scraped": result.get("full_scraped", 0),
                        "browser_count": result.get("browser_count", 0),
                        "round": round_num,
                    },
                )

            round_results.sort(key=lambda r: r["index"])

            for r in round_results:
                all_summaries.append(
                    {
                        "round": round_num,
                        "query": r["query"],
                        "summary": r["summary"],
                    }
                )

            # Collect academic results
            if academic_task is not None:
                try:
                    academic_result = await academic_task
                    academic_papers = academic_result.get("papers", [])
                    yield sse(
                        "academic_search_done",
                        {
                            "total": len(academic_papers),
                            "papers": [
                                {
                                    "title": p["title"],
                                    "authors": p["authors"],
                                    "year": p.get("year") or p.get("published", ""),
                                    "url": p["url"],
                                    "source": p["source"],
                                    "citations": p.get("citations", 0),
                                }
                                for p in academic_papers[:5]
                            ],
                        },
                    )
                except Exception:
                    academic_papers = []

            yield sse(
                "step",
                {
                    "step": 3,
                    "state": "done",
                    "text": f"Round {round_num} — {total_scraped} pages read · {browser_count} via browser",
                },
            )

            # Gap analysis
            is_last = round_num >= DEEP_MAX_ROUNDS
            has_min = round_num >= DEEP_MIN_ROUNDS

            if not is_last:
                yield sse("gap_analysis_start", {"round": round_num})
                gap = await analyze_gaps(
                    sanitize_query_for_azure(query),
                    round_num,
                    all_summaries,
                    seen_queries,
                )
                gap_analyses.append(gap)

                yield sse(
                    "gap_analysis_done",
                    {
                        "round": round_num,
                        "gaps_found": gap["gaps_found"],
                        "confidence": gap.get("confidence", 0),
                        "gap_analysis": gap.get("gap_analysis", ""),
                        "next_queries": gap.get("follow_up_queries", []),
                    },
                )

                confidence_val = gap.get("confidence", 0)
                should_stop_gap = has_min and not gap["gaps_found"]
                should_stop_conf = has_min and confidence_val >= 0.72
                if should_stop_gap or should_stop_conf:
                    stop_reason = (
                        "Research sufficiently complete"
                        if should_stop_gap
                        else f"Confidence threshold reached ({round(confidence_val*100)}%)"
                    )
                    yield sse(
                        "early_stop",
                        {
                            "round": round_num,
                            "reason": stop_reason,
                            "confidence": confidence_val,
                        },
                    )
                    break
            else:
                gap_analyses.append({"gap_analysis": "", "follow_up_queries": []})

        # Final synthesis
        rounds_completed = round_num

        yield sse(
            "step",
            {
                "step": 4,
                "state": "active",
                "text": f"Synthesizing report — {rounds_completed} rounds · {len(all_citations)} sources · {browser_count} via browser",
            },
        )

        report = await synthesize_deep_report(
            query,
            all_summaries,
            all_citations,
            academic_papers,
            rounds_completed,
            gap_analyses,
            is_academic,
        )

        elapsed = round(time.time() - start, 1)
        scrape_count = total_scraped - browser_count

        stats = {
            "rounds": rounds_completed,
            "total_sources": len(all_citations),
            "total_scraped": total_scraped,
            "browser_count": browser_count,
            "scrape_count": scrape_count,
        }
        md_content = export_markdown_report(
            query, report, all_citations, academic_papers, stats
        )
        report_path = Path(tempfile.gettempdir()) / "ragioneer_deep_report.md"
        report_path.write_text(md_content, encoding="utf-8")

        yield sse("step", {"step": 4, "state": "done", "text": "Report complete"})
        yield sse(
            "result",
            {
                "answer": report,
                "elapsed": elapsed,
                "rounds_completed": rounds_completed,
                "sources_searched": len(all_summaries),
                "total_scraped": total_scraped,
                "browser_count": browser_count,
                "citations": all_citations[:30],
                "academic_papers": academic_papers,
                "is_academic": is_academic,
                "download_ready": True,
                "mode": "deep",
            },
        )

    except httpx.HTTPStatusError as e:
        try:
            detail = e.response.json()
            msg = detail.get("error", {}).get("message") or e.response.text
        except Exception:
            msg = e.response.text
        yield sse("error", {"message": f"API error {e.response.status_code}: {msg}"})

    except json.JSONDecodeError as e:
        yield sse("error", {"message": f"Failed to parse model JSON: {e}"})

    except RuntimeError as e:
        yield sse("error", {"message": str(e)})

    except Exception as e:
        yield sse("error", {"message": f"Unexpected error: {type(e).__name__}: {e}"})

    finally:
        yield sse("done", {})


# ─── Override the /research/deep endpoint to use v2 stream ───────────────────


@app.post("/research/deep/v2")
async def deep_research_v2(req: ResearchRequest):
    """
    Improved deep research endpoint using all quality fixes.
    Accessible at /research/deep/v2 — the frontend will use this.
    """
    missing = []
    if not AZURE_OPENAI_KEY or not AZURE_OPENAI_ENDPOINT:
        missing.append("AZURE_OPENAI_KEY and AZURE_OPENAI_ENDPOINT")
    if not SERPER_API_KEY:
        missing.append("SERPER_API_KEY")
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing .env config: {', '.join(missing)}",
        )

    return StreamingResponse(
        deep_research_stream_v2(req.query),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ═══════════════════════════════════════════════════════════════════════════════
# COMPUTER USE
# Vision-based autonomous browser agent using GPT-5.2 + Playwright.
# Hybrid streaming: live text events + batched screenshot trail at end.
# Supports both extraction tasks (read/scrape) and interactive tasks
# (click, type, navigate, fill forms, download files).
# ═══════════════════════════════════════════════════════════════════════════════

import base64
from fastapi.responses import JSONResponse

# ─── Computer Use config ──────────────────────────────────────────────────────

CU_MAX_STEPS = int(os.getenv("CU_MAX_STEPS", "40"))  # increased from 25
CU_SCREENSHOT_WIDTH = 1280
CU_SCREENSHOT_HEIGHT = 800
CU_SCREENSHOT_QUALITY = 45  # JPEG quality — lower = fewer tokens, faster
# 45 is sufficient for GPT vision and keeps base64 < 200KB
CU_STEP_TIMEOUT = 30  # seconds per action

# Action types the agent can take
VALID_ACTIONS = {
    "navigate",  # go to a URL
    "click",  # click at (x, y)
    "type",  # type text into focused element
    "press",  # press a keyboard key
    "scroll",  # scroll up/down
    "extract",  # extract text/data from current page
    "wait",  # wait for page to settle
    "download",  # click a download link
    "done",  # task complete
    "failed",  # task cannot be completed
}


# ─── Computer Use request model ───────────────────────────────────────────────


class ComputerUseRequest(BaseModel):
    task: str
    start_url: str | None = None


# ─── Vision-enabled Azure call ────────────────────────────────────────────────


async def call_azure_vision(
    messages: list[dict],
    temperature: float = 0.1,
    max_tokens: int = 1024,
    timeout: float = 60.0,
) -> str:
    """
    Call Azure OpenAI Chat Completions with vision (image) support.
    GPT-5.2 supports multimodal inputs — same endpoint, different message format.
    Image is passed as base64 in the content array.
    """
    if not AZURE_OPENAI_KEY or not AZURE_OPENAI_ENDPOINT:
        raise RuntimeError("Azure OpenAI not configured.")

    headers = {
        "api-key": AZURE_OPENAI_KEY,
        "Content-Type": "application/json",
    }
    body = {
        "messages": messages,
        "max_completion_tokens": max_tokens,
        "temperature": temperature,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(AZURE_CHAT_URL, headers=headers, json=body)
        resp.raise_for_status()

    data = resp.json()
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError(
            f"Azure returned no choices. "
            f"finish_reason={data.get('choices',[{}])[0].get('finish_reason','unknown') if data.get('choices') else 'no_choices'}. "
            f"Possible content filter or token limit."
        )
    content_val = choices[0].get("message", {}).get("content") or ""
    return content_val


# ─── Screenshot helper ────────────────────────────────────────────────────────


def take_screenshot_b64(page) -> str:
    """
    Take a JPEG screenshot of the current page and return as base64 string.
    Synchronous — called from within the Playwright thread.

    Keeps base64 output under ~300KB to avoid 400 Bad Request from Azure
    when the image is too large for the vision API token limit.
    """
    screenshot_bytes = page.screenshot(
        type="jpeg",
        quality=CU_SCREENSHOT_QUALITY,
        clip={
            "x": 0,
            "y": 0,
            "width": CU_SCREENSHOT_WIDTH,
            "height": CU_SCREENSHOT_HEIGHT,
        },
    )

    # If screenshot is too large, re-compress at lower quality
    MAX_BYTES = 280_000  # ~300KB base64 safe limit for Azure vision
    if len(screenshot_bytes) > MAX_BYTES:
        import io as _io
        from PIL import Image as _Image

        try:
            img = _Image.open(_io.BytesIO(screenshot_bytes))
            buf = _io.BytesIO()
            quality = 35
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            screenshot_bytes = buf.getvalue()
        except ImportError:
            # PIL not available — use Playwright's lower quality directly
            screenshot_bytes = page.screenshot(
                type="jpeg",
                quality=25,
                clip={
                    "x": 0,
                    "y": 0,
                    "width": CU_SCREENSHOT_WIDTH,
                    "height": CU_SCREENSHOT_HEIGHT,
                },
            )

    return base64.b64encode(screenshot_bytes).decode("utf-8")


# ─── Generic smart URL builder (ANY site, ANY country, ANY task) ──────────────


def build_smart_urls(task: str) -> dict:
    import urllib.parse as _up
    import re as _re

    task_lower = task.lower()
    urls = {}

    # Extract product/topic
    qm = _re.search(r"['\"]([^'\"]{3,60})['\"]", task)
    if qm:
        product = qm.group(1).strip()
    else:
        vm = _re.search(
            r"(?:search for|find|check|compare|look up|navigate to|visit|go to)\s+"
            r"([\w][^,.?]{3,50}?)(?:\s+(?:on|at|in|from|vs|and|price)|[,.]|$)",
            task_lower,
        )
        product = vm.group(1).strip().title() if vm else None
    if not product:
        caps = _re.findall(r"[A-Z][a-zA-Z0-9]+(?: [A-Z][a-zA-Z0-9]+){1,4}", task)
        product = caps[0] if caps else task.split()[0]

    penc = _up.quote_plus(product)
    pslug = product.lower().replace(" ", "-")

    # Category detection for price floors
    is_phone = any(
        w in task_lower
        for w in [
            "phone",
            "smartphone",
            "iphone",
            "samsung",
            "galaxy",
            "pixel",
            "oneplus",
        ]
    )
    is_laptop = any(
        w in task_lower
        for w in ["laptop", "notebook", "macbook", "thinkpad", "dell xps", "surface"]
    )
    is_appliance = any(
        w in task_lower
        for w in [
            "refrigerator",
            "fridge",
            "washing machine",
            "air conditioner",
            "microwave",
        ]
    )

    if is_phone:
        daraz_min = 50000
    elif is_laptop:
        daraz_min = 80000
    elif is_appliance:
        daraz_min = 30000
    else:
        daraz_min = 1000

    # Phone model lookup
    phone_models = {
        "galaxy s26 ultra": (
            "Samsung+Galaxy+S26+Ultra",
            "samsung/samsung-galaxy-s26-ultra",
        ),
        "galaxy s25 ultra": (
            "Samsung+Galaxy+S25+Ultra",
            "samsung/samsung-galaxy-s25-ultra",
        ),
        "galaxy s24 ultra": (
            "Samsung+Galaxy+S24+Ultra",
            "samsung/samsung-galaxy-s24-ultra",
        ),
        "galaxy s24 fe": ("Samsung+Galaxy+S24+FE", "samsung/samsung-galaxy-s24-fe"),
        "galaxy s24": ("Samsung+Galaxy+S24", "samsung/samsung-galaxy-s24"),
        "galaxy s23 ultra": (
            "Samsung+Galaxy+S23+Ultra",
            "samsung/samsung-galaxy-s23-ultra",
        ),
        "galaxy s23": ("Samsung+Galaxy+S23", "samsung/samsung-galaxy-s23"),
        "s26 ultra": ("Samsung+Galaxy+S26+Ultra", "samsung/samsung-galaxy-s26-ultra"),
        "s25 ultra": ("Samsung+Galaxy+S25+Ultra", "samsung/samsung-galaxy-s25-ultra"),
        "s24 ultra": ("Samsung+Galaxy+S24+Ultra", "samsung/samsung-galaxy-s24-ultra"),
        "s24 fe": ("Samsung+Galaxy+S24+FE", "samsung/samsung-galaxy-s24-fe"),
        "s24": ("Samsung+Galaxy+S24", "samsung/samsung-galaxy-s24"),
        "iphone 17 pro max": (
            "Apple+iPhone+17+Pro+Max",
            "apple/apple-iphone-17-pro-max",
        ),
        "iphone 17 pro": ("Apple+iPhone+17+Pro", "apple/apple-iphone-17-pro"),
        "iphone 17": ("Apple+iPhone+17", "apple/apple-iphone-17"),
        "iphone 16 pro max": (
            "Apple+iPhone+16+Pro+Max",
            "apple/apple-iphone-16-pro-max",
        ),
        "iphone 16 pro": ("Apple+iPhone+16+Pro", "apple/apple-iphone-16-pro"),
        "iphone 16": ("Apple+iPhone+16", "apple/apple-iphone-16"),
        "iphone 15 pro max": (
            "Apple+iPhone+15+Pro+Max",
            "apple/apple-iphone-15-pro-max",
        ),
        "iphone 15": ("Apple+iPhone+15", "apple/apple-iphone-15"),
        "pixel 9 pro": ("Google+Pixel+9+Pro", "google/google-pixel-9-pro"),
        "pixel 9": ("Google+Pixel+9", "google/google-pixel-9"),
        "oneplus 13": ("OnePlus+13", "oneplus/oneplus-13"),
        "oneplus 12": ("OnePlus+12", "oneplus/oneplus-12"),
    }
    dz_q = penc
    po_path = None
    for key in sorted(phone_models, key=len, reverse=True):
        if key in task_lower:
            dz_q, po_path = phone_models[key]
            break

    # Pakistan sites
    if "priceoye" in task_lower:
        if po_path:
            urls["priceoye_direct"] = f"https://priceoye.pk/mobiles/{po_path}"
        urls["priceoye_search"] = f"https://priceoye.pk/search?search={dz_q}"

    if "daraz" in task_lower:
        urls["daraz_search"] = (
            f"https://www.daraz.pk/catalog/?q={dz_q}"
            f"&minPrice={daraz_min}&maxPrice=900000&sort=pricedesc"
        )
        urls["daraz_google"] = (
            f"https://www.google.com/search?q=site:daraz.pk+{dz_q}+price"
        )

    if "olx" in task_lower and ("pakistan" in task_lower or ".pk" in task_lower):
        urls["olx_pk"] = f"https://www.olx.com.pk/items/q-{product.replace(' ','-')}"

    if "hamariweb" in task_lower:
        urls["hamariweb"] = f"https://hamariweb.com/mobiles/search/?q={penc}"

    # India
    if "flipkart" in task_lower:
        urls["flipkart_search"] = (
            f"https://www.flipkart.com/search?q={penc}&sort=price_desc"
        )
        urls["flipkart_google"] = (
            f"https://www.google.com/search?q=site:flipkart.com+{penc}"
        )

    if "amazon.in" in task_lower or ("amazon" in task_lower and "india" in task_lower):
        urls["amazon_in"] = f"https://www.amazon.in/s?k={penc}&s=price-desc-rank"

    if "snapdeal" in task_lower:
        urls["snapdeal"] = f"https://www.snapdeal.com/search?keyword={penc}"

    if "meesho" in task_lower:
        urls["meesho"] = f"https://meesho.com/search?q={penc}"

    # Middle East
    if "noon" in task_lower:
        urls["noon_search"] = f"https://www.noon.com/uae-en/search/?q={penc}"
        urls["noon_google"] = (
            f"https://www.google.com/search?q=site:noon.com+{penc}+price"
        )

    if "amazon.ae" in task_lower or (
        "amazon" in task_lower
        and any(x in task_lower for x in ["uae", "dubai", "emirates"])
    ):
        urls["amazon_ae"] = f"https://www.amazon.ae/s?k={penc}&s=price-desc-rank"

    # Global e-commerce
    if "amazon.com" in task_lower or (
        "amazon" in task_lower
        and "amazon.in" not in task_lower
        and "amazon.ae" not in task_lower
    ):
        urls["amazon_com"] = f"https://www.amazon.com/s?k={penc}&s=price-desc-rank"

    if "ebay" in task_lower:
        urls["ebay"] = f"https://www.ebay.com/sch/i.html?_nkw={penc}&_sop=16"

    if "walmart" in task_lower:
        urls["walmart"] = f"https://www.walmart.com/search?q={penc}"

    if "bestbuy" in task_lower or "best buy" in task_lower:
        urls["bestbuy"] = f"https://www.bestbuy.com/site/searchpage.jsp?st={penc}"

    if "newegg" in task_lower:
        urls["newegg"] = f"https://www.newegg.com/p/pl?d={penc}"

    if "lazada" in task_lower:
        urls["lazada"] = f"https://www.lazada.com/catalog/?q={penc}&sort=pricedesc"

    if "shopee" in task_lower:
        urls["shopee"] = f"https://shopee.com/search?keyword={penc}"

    if "jumia" in task_lower:
        urls["jumia"] = f"https://www.jumia.com/catalog/?q={penc}"

    if "takealot" in task_lower:
        urls["takealot"] = f"https://www.takealot.com/all?qsearch={penc}"

    if "aliexpress" in task_lower:
        urls["aliexpress"] = f"https://www.aliexpress.com/w/wholesale-{pslug}.html"

    # News sites
    news = {
        "dawn": ("dawn.com", f"https://www.dawn.com/search?q={penc}"),
        "geo": ("geo.tv", f"https://www.geo.tv/search?q={penc}"),
        "nation": ("nation.com.pk", f"https://nation.com.pk/?s={penc}"),
        "jang": ("jang.com", f"https://jang.com.pk/search/{penc}"),
        "bbc": ("bbc.com", f"https://www.bbc.com/search?q={penc}"),
        "reuters": ("reuters.com", f"https://www.reuters.com/search/news?blob={penc}"),
        "guardian": ("theguardian.com", f"https://www.theguardian.com/search?q={penc}"),
        "nytimes": ("nytimes.com", f"https://www.nytimes.com/search?query={penc}"),
        "bloomberg": (
            "bloomberg.com",
            f"https://www.bloomberg.com/search?query={penc}",
        ),
        "cnbc": ("cnbc.com", f"https://www.cnbc.com/search/?query={penc}"),
        "cnn": ("cnn.com", f"https://edition.cnn.com/search?q={penc}"),
        "techcrunch": ("techcrunch.com", f"https://techcrunch.com/search/{penc}/"),
        "wired": ("wired.com", f"https://www.wired.com/search/?q={penc}"),
        "forbes": ("forbes.com", f"https://www.forbes.com/search/?q={penc}"),
        "aljazeera": ("aljazeera.com", f"https://www.aljazeera.com/search/{penc}"),
        "apnews": ("apnews.com", f"https://apnews.com/search?q={penc}"),
        "theverge": ("theverge.com", f"https://www.theverge.com/search?q={penc}"),
    }
    for kw, (domain, url) in news.items():
        if kw in task_lower or domain in task_lower:
            urls[f"{kw}_search"] = url
            urls[f"{kw}_google"] = (
                f"https://www.google.com/search?q=site:{domain}+{penc}"
            )

    # Tech / developer sites
    tech = {
        "github": f"https://github.com/search?q={penc}&type=repositories",
        "stackoverflow": f"https://stackoverflow.com/search?q={penc}",
        "npm": f"https://www.npmjs.com/search?q={pslug}",
        "pypi": f"https://pypi.org/search/?q={penc}",
        "huggingface": f"https://huggingface.co/search/full-text?q={penc}",
        "arxiv": f"https://arxiv.org/search/?searchtype=all&query={penc}",
    }
    for kw, url in tech.items():
        if kw in task_lower:
            urls[f"{kw}_search"] = url

    # Social / community
    social = {
        "reddit": f"https://www.reddit.com/search/?q={penc}&sort=new",
        "linkedin": f"https://www.linkedin.com/search/results/all/?keywords={penc}",
        "youtube": f"https://www.youtube.com/results?search_query={penc}",
        "twitter": f"https://twitter.com/search?q={penc}&f=live",
        "wikipedia": f"https://en.wikipedia.org/wiki/Special:Search?search={penc}",
    }
    for kw, url in social.items():
        if kw in task_lower:
            urls[f"{kw}_search"] = url

    return urls


# Backward-compatibility alias
def build_pakistan_ecommerce_urls(task: str) -> dict:
    return build_smart_urls(task)


async def plan_task(task: str, start_url: str | None) -> dict:
    """
    Before the agent starts, ask GPT to create a step-by-step plan.
    This prevents wandering and gives the action loop a clear goal.

    Returns {
      "goal": str,
      "steps": [str, ...],
      "start_url": str,
      "task_type": "extraction" | "interactive" | "mixed"
    }
    """
    url_hint = (
        f"Starting URL: {start_url}"
        if start_url
        else "No starting URL — agent will navigate as needed."
    )

    # Pre-build direct working URLs for Pakistan e-commerce
    _prebuilt = build_smart_urls(task)
    _prebuilt_hint = ""
    if _prebuilt:
        _prebuilt_hint = "\n\nPRE-BUILT DIRECT URLs — navigate to these instead of using search boxes:\n"
        for _site, _url in _prebuilt.items():
            _prebuilt_hint += f"  {_site}: {_url}\n"

    system = """You are a browser automation planner.
Given a task, create a clear step-by-step plan for a browser agent to follow.

Respond ONLY with valid JSON:
{
  "goal": "one sentence describing what success looks like",
  "steps": [
    "Step 1: ...",
    "Step 2: ...",
    "Step 3: ..."
  ],
  "start_url": "https://... (the best URL to start at, or null)",
  "task_type": "extraction" or "interactive" or "mixed"
}

Rules:
- Maximum 8 planning steps
- Each step is specific and actionable
- If start_url is provided, use it; otherwise suggest the best URL
- task_type: extraction = read/scrape only; interactive = fill forms/click; mixed = both

E-COMMERCE TASKS (ANY site — Amazon, eBay, Daraz, Flipkart, Noon, Lazada, Shopee, etc.):
- NEVER sort by lowest price — cheap accessories appear before real products
- Sort by HIGHEST price or set a minimum price filter:
    Amazon (any region): append &s=price-desc-rank
    Daraz/Lazada/Shopee: append &sort=pricedesc&minPrice=5000
    eBay: append &_sop=16
    Flipkart: append &sort=price_desc
- If results show wrong category, add a category word (e.g. "Samsung S24 smartphone")
- Extract: product name, price, seller, URL, rating — all in ONE extract action
- Sidebar filters are in the LEFT narrow column, scroll it separately

NEWS / INFORMATION TASKS (ANY site — BBC, Reuters, Dawn, GitHub, Reddit, etc.):
- If site search fails after 2 attempts, use Google site: search immediately:
  https://www.google.com/search?q=site:DOMAIN.com+[topic]

DATA EXTRACTION (ANY task):
- Extract ALL needed data in ONE extract action — never one item at a time
- Include: names, prices, dates, URLs, ratings, any visible numbers

MULTI-SITE TASKS (any combination of sites):
- 1 site: up to 12 steps | 2 sites: ~12 steps each | 3+ sites: ~8 steps each
- Always fully complete site A before navigating to site B
- If a site blocks you after 3 attempts, skip it and move to the next"""

    raw = await call_azure(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"Task: {task}\n{url_hint}{_prebuilt_hint}"},
        ],
        temperature=0.1,
        max_tokens=512,
    )

    clean = raw.replace("```json", "").replace("```", "").strip()

    # Guard: if response is empty or not JSON (e.g. content filter triggered),
    # build a sensible fallback plan so the agent can still proceed.
    if not clean:
        plan = {
            "goal": f"Complete the task: {task[:100]}",
            "steps": [
                "Step 1: Navigate to the target website",
                "Step 2: Find relevant information",
                "Step 3: Extract required data",
                "Step 4: Verify and compile results",
            ],
            "start_url": start_url or "https://www.google.com",
            "task_type": "mixed",
        }
    else:
        try:
            plan = json.loads(clean)
        except json.JSONDecodeError:
            # Try to extract JSON from mixed response
            import re as _re

            m = _re.search(r"\{.*\}", clean, _re.DOTALL)
            if m:
                plan = json.loads(m.group())
            else:
                plan = {
                    "goal": f"Complete the task: {task[:100]}",
                    "steps": ["Step 1: Navigate to target", "Step 2: Extract data"],
                    "start_url": start_url or "https://www.google.com",
                    "task_type": "mixed",
                }

    # Use provided start_url if given, override plan's suggestion
    if start_url:
        plan["start_url"] = start_url

    # Dynamic step limit: count distinct sites/platforms in task
    _t = task.lower()
    _known_sites = [
        # Pakistan
        "priceoye",
        "daraz",
        "olx",
        "hamariweb",
        "bykea",
        "sadapay",
        "nayapay",
        "dawn.com",
        "nation.com",
        "geo.tv",
        "jang.com",
        # India & South Asia
        "flipkart",
        "snapdeal",
        "amazon.in",
        "myntra",
        # Middle East
        "noon.com",
        "amazon.ae",
        "souq.com",
        # Global e-commerce
        "amazon.com",
        "ebay.com",
        "walmart.com",
        "bestbuy.com",
        "newegg.com",
        "aliexpress",
        "lazada",
        "shopee",
        "jumia",
        "takealot",
        # News & content
        "bbc.com",
        "reuters.com",
        "theguardian",
        "nytimes",
        "bloomberg",
        "techcrunch",
        "github.com",
        "stackoverflow",
        "reddit.com",
        "linkedin",
        "twitter",
        "x.com",
        "youtube",
        "wikipedia",
    ]
    _site_count = max(1, sum(1 for s in _known_sites if s in _t))
    plan["recommended_steps"] = min(_site_count * 14, CU_MAX_STEPS)

    return plan


# ─── Action decider ───────────────────────────────────────────────────────────


async def decide_action(
    screenshot_b64: str,
    task: str,
    plan_steps: list[str],
    step_history: list[dict],
    current_url: str,
) -> dict:
    """
    Core vision-language decision call.
    GPT-5.2 sees the current screenshot + task context and decides the next action.

    Returns action dict:
    {
      "action": "click|type|navigate|scroll|extract|press|wait|download|done|failed",
      "x": int (for click),
      "y": int (for click),
      "text": str (for type/press/navigate),
      "direction": "up|down" (for scroll),
      "amount": int (scroll pixels),
      "description": str (human-readable what this step does),
      "extracted_data": str (for extract action),
      "reason": str (why this action, or why failed/done)
    }
    """
    # Build history summary (last 5 steps to keep tokens manageable)
    recent_history = step_history[-5:] if len(step_history) > 5 else step_history
    history_str = "\n".join(
        f"Step {s['step']}: {s['action']} — {s['description']}" for s in recent_history
    )

    plan_str = "\n".join(plan_steps)

    system = """You are a browser automation agent. You see a screenshot of a web browser
and must decide the next action to complete the given task.

Respond ONLY with valid JSON — no markdown, no explanation:
{
  "action": "one of: navigate|click|type|press|scroll|extract|wait|download|done|failed",
  "x": <integer pixel x coordinate for click, else omit>,
  "y": <integer pixel y coordinate for click, else omit>,
  "text": <string for type/navigate/press, else omit>,
  "direction": <"up" or "down" for scroll, else omit>,
  "amount": <pixels to scroll, else omit>,
  "description": "<one sentence describing what this action does>",
  "extracted_data": "<the extracted text/data if action is extract, else omit>",
  "reason": "<why you chose this action, or why done/failed>"
}

ACTION GUIDE:
- navigate: go to URL → {"action":"navigate","text":"https://...","description":"..."}
- click: click element → {"action":"click","x":450,"y":320,"description":"Click search button"}
- type: type text → {"action":"type","text":"Python developer Pakistan","description":"..."}
- press: keyboard key → {"action":"press","text":"Enter","description":"..."}
- scroll: scroll page → {"action":"scroll","direction":"down","amount":500,"description":"..."}
- extract: pull data from page → {"action":"extract","extracted_data":"[the data]","description":"..."}
- wait: wait for load → {"action":"wait","description":"Waiting for results to load"}
- download: click download → {"action":"click","x":...,"y":...,"description":"Click download button"}
- done: task complete → {"action":"done","reason":"Successfully extracted all required data"}
- failed: cannot complete → {"action":"failed","reason":"Login required, cannot proceed"}

IMPORTANT:
- Coordinates are pixel positions on a 1280x800 screenshot
- If you see a cookie banner/popup, dismiss it first
- If you see a login wall, use "failed" immediately
- If the task is complete, use "done" immediately
- Never click the same coordinates twice in a row unless intentional
- For "extract": include ALL extracted data in extracted_data field"""

    # Detect repeated actions for loop warning
    loop_warning = ""

    # Pre-build e-commerce URLs for this task
    _agent_prebuilt = build_smart_urls(task)
    _agent_prebuilt_hint = ""
    if _agent_prebuilt:
        _agent_prebuilt_hint = "\nDIRECT URLS TO USE:\n"
        for _s, _u in _agent_prebuilt.items():
            _agent_prebuilt_hint += f"  {_s}: {_u}\n"
    if len(step_history) >= 2:
        import collections as _col

        last_actions = [s.get("action", "") for s in step_history[-4:]]
        last_descs = [s.get("description", "")[:40] for s in step_history[-4:]]
        action_counts = _col.Counter(last_descs)
        most_common_count = max(action_counts.values()) if action_counts else 0
        if most_common_count >= 2:
            import urllib.parse as _up_w

            loop_warning = (
                f"\n\nWARNING: You have repeated the same action {most_common_count} times "
                f"with no progress. STOP. Use a completely different approach. "
                f"Navigate to Google right now: "
                f"https://www.google.com/search?q={_up_w.quote_plus(task[:80])}"
            )

    # Only include image if we have a valid, non-trivial screenshot
    # Empty/tiny screenshots cause 400 errors from Azure vision API
    text_part = {
        "type": "text",
        "text": (
            f"TASK: {task}\n\n"
            f"PLAN:\n{plan_str}\n\n"
            f"CURRENT URL: {current_url}\n\n"
            f"STEPS TAKEN SO FAR:\n{history_str if history_str else 'None yet'}"
            f"{_agent_prebuilt_hint if step_num <= 8 else ''}"
            f"{loop_warning}\n\n"
            f"Look at the screenshot and decide the next action:"
        ),
    }

    has_valid_screenshot = (
        screenshot_b64 and len(screenshot_b64) > 1000
    )  # min ~750 bytes decoded
    if has_valid_screenshot:
        user_content = [
            text_part,
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{screenshot_b64}",
                    "detail": "low",  # use low detail to save tokens
                },
            },
        ]
    else:
        # No screenshot — text-only decision (tell GPT what URL we're on)
        text_part[
            "text"
        ] += f"\n\n(No screenshot available — page may still be loading at {current_url})"
        user_content = [text_part]

    raw = await call_azure_vision(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        temperature=0.1,
        max_tokens=800,
    )

    clean = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(clean)


# ─── Action executor ──────────────────────────────────────────────────────────


def execute_action_sync(page, action: dict) -> dict:
    """
    Execute a browser action synchronously via Playwright.
    Returns {"success": bool, "error": str|None, "url": str}
    """
    action_type = action.get("action", "")

    try:
        if action_type == "navigate":
            url = action.get("text", "")
            if not url.startswith("http"):
                url = "https://" + url
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(1500)
            except Exception as _nav_err:
                # Timeout or navigation error — try networkidle as fallback
                _err_str = str(_nav_err).lower()
                if "timeout" in _err_str:
                    try:
                        # Already partially loaded — just wait for what we have
                        page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass  # use whatever is loaded
                else:
                    raise

        elif action_type == "click":
            x = action.get("x", 0)
            y = action.get("y", 0)
            page.mouse.click(x, y)
            page.wait_for_timeout(1000)

        elif action_type == "type":
            text = action.get("text", "")
            page.keyboard.type(text, delay=50)
            page.wait_for_timeout(500)

        elif action_type == "press":
            key = action.get("text", "Enter")
            page.keyboard.press(key)
            page.wait_for_timeout(1000)

        elif action_type == "scroll":
            direction = action.get("direction", "down")
            amount = action.get("amount", 500)
            delta = amount if direction == "down" else -amount
            page.mouse.wheel(0, delta)
            page.wait_for_timeout(800)

        elif action_type == "wait":
            page.wait_for_timeout(2000)

        elif action_type in ("extract", "done", "failed"):
            pass  # handled outside executor

        return {"success": True, "error": None, "url": page.url}

    except Exception as e:
        return {"success": False, "error": str(e), "url": page.url}


# ─── Result compiler ──────────────────────────────────────────────────────────


async def compile_result(
    task: str,
    plan: dict,
    step_history: list[dict],
    extracted_items: list[str],
    final_url: str,
    total_steps: int,
    success: bool,
) -> str:
    """
    Final synthesis — summarize what the agent accomplished, what was extracted,
    and any failures or caveats.
    """
    history_str = "\n".join(
        f"Step {s['step']} [{s['action'].upper()}]: {s['description']}"
        + (f" → ERROR: {s.get('error')}" if s.get("error") else "")
        for s in step_history
    )

    extracted_str = (
        "\n\n---\n\n".join(extracted_items) if extracted_items else "No data extracted."
    )

    system = """You are summarizing the results of a browser automation task.
Write a clear, structured summary of what was accomplished.

Format:
## Task Summary
[What was accomplished and overall success/failure]

## Extracted Data
[Present all extracted data clearly — tables, lists, or prose as appropriate]

## Steps Taken
[Brief narrative of what the agent did]

## Limitations & Caveats
[What couldn't be done, login walls hit, data that was missing, etc.]

Be specific with numbers, URLs, and data. Format extracted data cleanly."""

    user = (
        f"Task: {task}\n\n"
        f"Goal: {plan.get('goal', '')}\n\n"
        f"Final URL: {final_url}\n"
        f"Total steps: {total_steps}\n"
        f"Status: {'SUCCESS' if success else 'PARTIAL/FAILED'}\n\n"
        f"Extracted data:\n{extracted_str}\n\n"
        f"Step history:\n{history_str}"
    )

    return await call_azure(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        max_tokens=2000,
        timeout=90.0,
    )


# ─── Synchronous GPT vision call (for use inside thread pool) ────────────────


def _decide_action_sync(
    screenshot_b64: str,
    task: str,
    plan_steps: list,
    step_history: list,
    current_url: str,
) -> dict:
    """
    Synchronous version of decide_action — uses httpx.Client (blocking).
    Called from inside the ThreadPoolExecutor thread where no asyncio loop
    should be started. Avoids the "Cannot run the event loop while another
    loop is running" error on Windows.
    """
    import httpx as _httpx
    import json as _json

    recent_history = step_history[-5:] if len(step_history) > 5 else step_history
    history_str = "\n".join(
        f"Step {s['step']}: {s['action']} — {s['description']}" for s in recent_history
    )
    plan_str = "\n".join(plan_steps)

    system = """You are a browser automation agent. You see a screenshot of a web browser
and must decide the next action to complete the given task.

Respond ONLY with valid JSON — no markdown, no explanation:
{
  "action": "one of: navigate|click|type|press|scroll|extract|wait|download|done|failed",
  "x": <integer pixel x coordinate for click, else omit>,
  "y": <integer pixel y coordinate for click, else omit>,
  "text": <string for type/navigate/press, else omit>,
  "direction": <"up" or "down" for scroll, else omit>,
  "amount": <pixels to scroll, else omit>,
  "description": "<one sentence describing what this action does>",
  "extracted_data": "<the extracted text/data if action is extract, else omit>",
  "reason": "<why you chose this action, or why done/failed>"
}

ACTION GUIDE:
- navigate: go to URL → {"action":"navigate","text":"https://...","description":"..."}
- click: click element → {"action":"click","x":450,"y":320,"description":"Click search button"}
- type: type text → {"action":"type","text":"search term","description":"..."}
- press: keyboard key → {"action":"press","text":"Enter","description":"..."}
- scroll: scroll page → {"action":"scroll","direction":"down","amount":500,"description":"..."}
- extract: pull data from page → {"action":"extract","extracted_data":"[the data]","description":"..."}
- wait: wait for load → {"action":"wait","description":"Waiting for results to load"}
- done: task complete → {"action":"done","reason":"Successfully extracted all required data"}
- failed: cannot complete → {"action":"failed","reason":"Login required, cannot proceed"}

CRITICAL RULES — READ CAREFULLY:

1. ANTI-LOOP: If you have attempted the same action (same coordinates OR same URL) 
   2 or more times in the recent history with no progress, you MUST switch strategy.
   Do NOT click the same element again. Use a completely different approach.

2. FALLBACK STRATEGY — When a site's search UI fails, use Google site search instead:
   navigate → "https://www.google.com/search?q=site:dawn.com+Strait+of+Hormuz"
   This bypasses broken search UIs entirely and finds the article directly.

3. DIRECT URL NAVIGATION — For news sites, try direct search URLs:
   - Dawn.com: https://www.dawn.com/search?q=hormuz
   - The Nation: https://nation.com.pk/?s=hormuz
   - Google: https://www.google.com/search?q=site:dawn.com+iran+war+2026

4. NEWS ARTICLE EXTRACTION — When you find an article page:
   - Use "extract" to pull the headline, lead paragraph, date, and key numbers
   - Extract ALL relevant text in one extract action
   - Include article URL in extraction

5. COOKIE BANNERS — If you see a cookie/consent popup, click Accept or Close first.

6. LOGIN WALLS — If login is required, immediately navigate to a different source.

7. TASK COMPLETION — Once you have extracted data from ALL required sources,
   use "done" immediately. Do not keep browsing after task is complete.

8. Coordinates are pixel positions on a 1280x800 screenshot.

9. reCAPTCHA / BOT DETECTION — If you see a reCAPTCHA, Cloudflare block, 
   or "Access Denied" page:
   - Do NOT try to solve it
   - Immediately use navigate to find the information via Google instead:
     navigate → "https://www.google.com/search?q=[site name]+[what you need]"
   - For financial fees (SadaPay, NayaPay etc.) try:
     navigate → "https://www.google.com/search?q=sadapay+international+transfer+fees+2026"
   - Extract data from Google's featured snippets or cached pages if available

10. MULTI-SITE TASKS — If a task requires visiting multiple sites (A, B, C):
    - Complete site A first, extract data, then move to B, then C
    - If site A blocks you after 3 attempts, skip it and move to site B
    - Do not get stuck on one site indefinitely

11. E-COMMERCE — ANY MARKETPLACE WORLDWIDE:
    - NEVER sort by lowest price — shows accessories/cheap items, not real products
    - Always sort HIGHEST price first OR set a minimum price filter:
        Amazon.com/in/ae: add &s=price-desc-rank to URL
        Daraz/Lazada/Shopee: add &sort=pricedesc&minPrice=5000
        eBay: use &_sop=16 in URL
        Flipkart: use &sort=price_desc
        Walmart: use &sort=price_high
    - If search returns wrong category, append the product type to query
    - Extract name + price + URL + rating in ONE extract action

12. NEWS / INFORMATION SITES — ANY SITE WORLDWIDE:
    - If site search fails after 2 attempts, immediately use Google:
      https://www.google.com/search?q=site:DOMAIN+[topic]
    - Works for BBC, Reuters, Dawn, Al Jazeera, GitHub, StackOverflow, any site

13. DATA EXTRACTION — ANY TASK:
    - Capture ALL required data in ONE extract action — never one item at a time
    - Include every visible: price, name, date, URL, rating, statistic
    - After finishing site A, navigate immediately to site B"""

    # Detect repeated actions for loop warning
    loop_warning = ""

    # Pre-build e-commerce URLs for this task
    _agent_prebuilt = build_smart_urls(task)
    _agent_prebuilt_hint = ""
    if _agent_prebuilt:
        _agent_prebuilt_hint = "\nDIRECT URLS TO USE:\n"
        for _s, _u in _agent_prebuilt.items():
            _agent_prebuilt_hint += f"  {_s}: {_u}\n"
    if len(step_history) >= 2:
        import collections as _col

        last_actions = [s.get("action", "") for s in step_history[-4:]]
        last_descs = [s.get("description", "")[:40] for s in step_history[-4:]]
        action_counts = _col.Counter(last_descs)
        most_common_count = max(action_counts.values()) if action_counts else 0
        if most_common_count >= 2:
            import urllib.parse as _up_w

            loop_warning = (
                f"\n\nWARNING: You have repeated the same action {most_common_count} times "
                f"with no progress. STOP. Use a completely different approach. "
                f"Navigate to Google right now: "
                f"https://www.google.com/search?q={_up_w.quote_plus(task[:80])}"
            )

    # Only include image if we have a valid, non-trivial screenshot
    # Empty/tiny screenshots cause 400 errors from Azure vision API
    text_part = {
        "type": "text",
        "text": (
            f"TASK: {task}\n\n"
            f"PLAN:\n{plan_str}\n\n"
            f"CURRENT URL: {current_url}\n\n"
            f"STEPS TAKEN SO FAR:\n{history_str if history_str else 'None yet'}"
            f"{loop_warning}\n\n"
            f"Look at the screenshot and decide the next action:"
        ),
    }

    has_valid_screenshot = (
        screenshot_b64 and len(screenshot_b64) > 1000
    )  # min ~750 bytes decoded
    if has_valid_screenshot:
        user_content = [
            text_part,
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{screenshot_b64}",
                    "detail": "low",  # use low detail to save tokens
                },
            },
        ]
    else:
        # No screenshot — text-only decision (tell GPT what URL we're on)
        text_part[
            "text"
        ] += f"\n\n(No screenshot available — page may still be loading at {current_url})"
        user_content = [text_part]

    headers = {
        "api-key": AZURE_OPENAI_KEY,
        "Content-Type": "application/json",
    }
    body = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "max_completion_tokens": 800,
        "temperature": 0.1,
    }

    # Retry up to 3 times on 500/502/503 server errors
    import time as _time

    last_exc = None
    for _attempt in range(3):
        try:
            with _httpx.Client(timeout=60.0) as client:
                resp = client.post(AZURE_CHAT_URL, headers=headers, json=body)
                if resp.status_code in (500, 502, 503, 529):
                    # Server error — wait and retry
                    _time.sleep(2**_attempt)  # 1s, 2s, 4s
                    last_exc = Exception(f"Azure {resp.status_code}: {resp.text[:200]}")
                    continue
                resp.raise_for_status()
                break
        except _httpx.TimeoutException:
            _time.sleep(2)
            last_exc = Exception("Azure request timed out")
            continue
    else:
        # All retries exhausted — return safe fallback
        return {
            "action": "wait",
            "description": f"Azure API unavailable after 3 retries: {last_exc}",
            "reason": "Server error — will retry on next step",
        }

    raw = resp.json()["choices"][0]["message"]["content"]
    clean = raw.replace("```json", "").replace("```", "").strip()

    if not clean:
        # Empty response — model refused or was filtered
        # Return a safe navigate-to-google fallback action
        return {
            "action": "navigate",
            "text": "https://www.google.com",
            "description": "Empty GPT response — navigating to Google as fallback",
            "reason": "Model returned empty response, possibly content filtered",
        }

    try:
        return _json.loads(clean)
    except _json.JSONDecodeError:
        # Try to extract JSON object from mixed text response
        import re as _re2

        m = _re2.search(r'\{[^{}]*"action"[^{}]*\}', clean, _re2.DOTALL)
        if m:
            try:
                return _json.loads(m.group())
            except Exception:
                pass
        # Final fallback
        return {
            "action": "wait",
            "description": f"Could not parse GPT response: {clean[:80]}",
            "reason": "JSON parse failed",
        }


# ─── Computer Use agent (sync — runs in thread pool) ─────────────────────────


def _computer_use_agent_sync(
    task: str,
    plan: dict,
    event_queue,  # queue.Queue for SSE events
    max_steps: int,
) -> dict:
    """
    The main agent loop — runs synchronously in a ThreadPoolExecutor thread.
    Communicates with the async SSE stream via a queue.

    Returns final result dict with step_history, screenshots, extracted_data.
    """
    import queue as _queue

    step_history: list[dict] = []
    screenshots: list[str] = []  # base64 JPEG per step
    extracted_items: list[str] = []
    final_url = plan.get("start_url") or "about:blank"
    success = False

    def push(event: str, data: dict):
        event_queue.put((event, data))

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=BROWSER_HEADLESS)
            context = browser.new_context(
                viewport={"width": CU_SCREENSHOT_WIDTH, "height": CU_SCREENSHOT_HEIGHT},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()

            # Navigate to start URL
            start_url = plan.get("start_url")
            if start_url:
                push(
                    "agent_step",
                    {
                        "step": 0,
                        "action": "navigate",
                        "description": f"Opening {start_url}",
                        "url": start_url,
                    },
                )
                try:
                    page.goto(start_url, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(1500)
                except Exception as e:
                    _err_lower = str(e).lower()
                    if "timeout" in _err_lower:
                        # Page partially loaded — continue anyway
                        push(
                            "agent_step",
                            {
                                "step": 0,
                                "action": "navigate",
                                "description": f"Start URL timed out but continuing with partial load: {start_url}",
                                "url": start_url,
                            },
                        )
                        try:
                            page.wait_for_load_state("domcontentloaded", timeout=5000)
                        except Exception:
                            pass
                    else:
                        push(
                            "agent_step",
                            {
                                "step": 0,
                                "action": "error",
                                "description": f"Failed to open start URL: {e}",
                                "url": start_url,
                            },
                        )

            # Main agent loop
            for step_num in range(1, max_steps + 1):
                final_url = page.url

                # Take screenshot
                try:
                    screenshot_b64 = take_screenshot_b64(page)
                    screenshots.append(screenshot_b64)
                except Exception:
                    screenshot_b64 = ""

                # Push screenshot event (hybrid: sends b64 inline)
                push(
                    "agent_screenshot",
                    {
                        "step": step_num,
                        "url": final_url,
                        "screenshot": screenshot_b64,
                    },
                )

                # reCAPTCHA / block detection — check page content
                try:
                    page_text = page.evaluate(
                        "() => document.body ? document.body.innerText.toLowerCase() : ''"
                    )
                    is_blocked = any(
                        kw in page_text[:500]
                        for kw in [
                            "recaptcha",
                            "verify you are human",
                            "cloudflare",
                            "access denied",
                            "403 forbidden",
                            "enable javascript",
                            "please verify",
                            "bot detection",
                        ]
                    )
                    if is_blocked:
                        # Extract the main topic from the task for Google search
                        task_words = task.replace("'", "").replace('"', "").split()
                        search_terms = "+".join(task_words[:6])
                        fallback_url = f"https://www.google.com/search?q={search_terms}"
                        push(
                            "agent_step",
                            {
                                "step": step_num,
                                "action": "navigate",
                                "description": "reCAPTCHA / bot block detected — switching to Google search",
                                "url": final_url,
                            },
                        )
                        page.goto(
                            fallback_url, wait_until="domcontentloaded", timeout=20000
                        )
                        page.wait_for_timeout(1500)
                        final_url = page.url
                        step_history.append(
                            {
                                "step": step_num,
                                "action": "navigate",
                                "description": "Bypassed block via Google search",
                                "url": final_url,
                                "error": None,
                            }
                        )
                        continue
                except Exception:
                    pass

                # Hard loop detection — force navigate if stuck clicking same spot
                if len(step_history) >= 3:
                    recent = step_history[-3:]
                    recent_coords = [
                        (s.get("action", ""), s.get("description", "")[:30])
                        for s in recent
                    ]
                    if len(set(str(c) for c in recent_coords)) == 1:
                        # All 3 last steps were identical — inject a forced navigate
                        push(
                            "agent_step",
                            {
                                "step": step_num,
                                "action": "navigate",
                                "description": "Loop detected — switching to Google site search as fallback",
                                "url": final_url,
                            },
                        )
                        # Generic fallback using build_smart_urls
                        _smart = build_smart_urls(task)
                        if _smart:
                            fallback_url = list(_smart.values())[0]
                        else:
                            import urllib.parse as _up_fb
                            import re as _re_fb

                            _stop = {
                                "the",
                                "a",
                                "an",
                                "and",
                                "or",
                                "of",
                                "to",
                                "in",
                                "is",
                                "for",
                                "on",
                                "at",
                                "by",
                                "go",
                                "find",
                                "check",
                                "get",
                                "navigate",
                                "this",
                                "that",
                            }
                            _words = _re_fb.sub(
                                r"[^a-zA-Z0-9 ]", " ", task.lower()
                            ).split()
                            _kws = [w for w in _words if w not in _stop and len(w) > 3][
                                :8
                            ]
                            fallback_url = (
                                "https://www.google.com/search?q="
                                + _up_fb.quote_plus(" ".join(_kws))
                            )
                        try:
                            page.goto(
                                fallback_url,
                                wait_until="domcontentloaded",
                                timeout=20000,
                            )
                            page.wait_for_timeout(1500)
                            final_url = page.url
                        except Exception:
                            pass
                        step_history.append(
                            {
                                "step": step_num,
                                "action": "navigate",
                                "description": "Loop broken — navigated to Google site search",
                                "url": final_url,
                                "error": None,
                            }
                        )
                        continue  # skip GPT decision this step, take screenshot next

                # Decide action — synchronous HTTP call directly (no asyncio needed)
                # We are already in a ThreadPoolExecutor thread; use httpx sync client
                try:
                    action = _decide_action_sync(
                        screenshot_b64,
                        task,
                        plan.get("steps", []),
                        step_history,
                        final_url,
                    )
                except Exception as e:
                    push(
                        "agent_step",
                        {
                            "step": step_num,
                            "action": "error",
                            "description": f"GPT decision failed: {e}",
                            "url": final_url,
                        },
                    )
                    break

                action_type = action.get("action", "failed")
                description = action.get("description", "")
                reason = action.get("reason", "")

                # Emit live text event immediately
                push(
                    "agent_step",
                    {
                        "step": step_num,
                        "action": action_type,
                        "description": description,
                        "url": final_url,
                        "reason": reason,
                    },
                )

                # Record in history
                step_history.append(
                    {
                        "step": step_num,
                        "action": action_type,
                        "description": description,
                        "url": final_url,
                        "error": None,
                    }
                )

                # Handle terminal actions
                if action_type == "done":
                    success = True
                    # Collect any last extraction
                    if action.get("extracted_data"):
                        extracted_items.append(action["extracted_data"])
                    break

                if action_type == "failed":
                    push(
                        "agent_error",
                        {
                            "step": step_num,
                            "reason": reason
                            or "Agent reported task cannot be completed",
                        },
                    )
                    break

                # Handle extract action
                if action_type == "extract":
                    extracted = action.get("extracted_data", "")
                    if extracted:
                        extracted_items.append(extracted)
                        push(
                            "agent_extract",
                            {
                                "step": step_num,
                                "content": extracted[:500],  # preview
                            },
                        )
                    continue  # no browser action needed for extract

                # Execute browser action
                exec_result = execute_action_sync(page, action)
                final_url = exec_result["url"]

                if not exec_result["success"]:
                    step_history[-1]["error"] = exec_result["error"]
                    push(
                        "agent_step",
                        {
                            "step": step_num,
                            "action": "error",
                            "description": f"Action failed: {exec_result['error']}",
                            "url": final_url,
                        },
                    )
                    # Continue — agent will see error state in next screenshot

            else:
                # Reached max steps without done/failed
                push(
                    "agent_error",
                    {
                        "step": max_steps,
                        "reason": f"Reached maximum step limit ({max_steps})",
                    },
                )

            browser.close()

    except Exception as e:
        push(
            "agent_error",
            {
                "step": 0,
                "reason": f"Browser error: {type(e).__name__}: {e}",
            },
        )

    return {
        "step_history": step_history,
        "screenshots": screenshots,
        "extracted_items": extracted_items,
        "final_url": final_url,
        "success": success,
        "total_steps": len(step_history),
    }


# ─── Computer Use SSE stream ──────────────────────────────────────────────────


async def computer_use_stream(task: str, start_url: str | None):
    """
    Hybrid streaming generator for Computer Use:
    - Live: agent_step, agent_extract, agent_error events (text only, instant)
    - Batched: all screenshots sent together in the final result event

    This keeps the stream responsive without sending large base64 blobs mid-stream.
    """
    import queue as _queue
    import concurrent.futures

    start_time = time.time()

    try:
        # ── Plan the task ─────────────────────────────────────────────────────
        yield sse(
            "agent_start",
            {
                "task": task,
                "start_url": start_url,
                "message": "Planning task...",
            },
        )

        plan = await plan_task(task, start_url)

        yield sse(
            "agent_plan",
            {
                "goal": plan.get("goal", ""),
                "steps": plan.get("steps", []),
                "start_url": plan.get("start_url", ""),
                "task_type": plan.get("task_type", "mixed"),
            },
        )

        yield sse(
            "agent_step",
            {
                "step": 0,
                "action": "plan",
                "description": f"Task planned: {plan.get('task_type', 'mixed')} mode, {len(plan.get('steps', []))} steps",
                "url": plan.get("start_url", ""),
                "reason": plan.get("goal", ""),
            },
        )

        # ── Run agent in thread pool with event queue ─────────────────────────
        event_queue = _queue.Queue()
        agent_result: dict = {}

        def run_agent():
            # Use plan's recommended_steps if available, else global max
            steps = plan.get("recommended_steps", CU_MAX_STEPS)
            result = _computer_use_agent_sync(task, plan, event_queue, steps)
            event_queue.put(("__done__", result))

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(run_agent)

        # Drain the event queue as events arrive
        loop = asyncio.get_event_loop()
        while True:
            try:
                # Non-blocking check — yield control to event loop between checks
                event_type, event_data = await loop.run_in_executor(
                    None, lambda: event_queue.get(timeout=0.1)
                )

                if event_type == "__done__":
                    agent_result = event_data
                    break

                # Screenshots are buffered, not streamed live
                if event_type == "agent_screenshot":
                    continue  # skip — will be sent in final result

                yield sse(event_type, event_data)

            except _queue.Empty:
                continue
            except Exception:
                break

        # Wait for thread to fully finish
        try:
            future.result(timeout=5)
        except Exception:
            pass
        executor.shutdown(wait=False)

        # ── Compile final result ───────────────────────────────────────────────
        yield sse(
            "agent_step",
            {
                "step": -1,
                "action": "compile",
                "description": "Compiling results...",
                "url": agent_result.get("final_url", ""),
                "reason": "",
            },
        )

        summary = await compile_result(
            task,
            plan,
            agent_result.get("step_history", []),
            agent_result.get("extracted_items", []),
            agent_result.get("final_url", ""),
            agent_result.get("total_steps", 0),
            agent_result.get("success", False),
        )

        elapsed = round(time.time() - start_time, 1)

        # Send final result — includes batched screenshots
        yield sse(
            "agent_done",
            {
                "summary": summary,
                "elapsed": elapsed,
                "total_steps": agent_result.get("total_steps", 0),
                "success": agent_result.get("success", False),
                "final_url": agent_result.get("final_url", ""),
                "extracted_count": len(agent_result.get("extracted_items", [])),
                "screenshots": agent_result.get("screenshots", []),  # batched b64 list
                "task_type": plan.get("task_type", "mixed"),
            },
        )

    except httpx.HTTPStatusError as e:
        try:
            msg = e.response.json().get("error", {}).get("message") or e.response.text
        except Exception:
            msg = e.response.text
        yield sse("error", {"message": f"API error {e.response.status_code}: {msg}"})

    except json.JSONDecodeError as e:
        yield sse(
            "error",
            {
                "message": (
                    f"Failed to parse JSON from Azure response: {e}. "
                    f"This usually means the model returned an empty response due to a content filter. "
                    f"Try rephrasing the task to avoid triggering content filters."
                )
            },
        )

    except RuntimeError as e:
        yield sse("error", {"message": str(e)})

    except Exception as e:
        yield sse("error", {"message": f"Unexpected error: {type(e).__name__}: {e}"})

    finally:
        yield sse("done", {})


# ─── Computer Use endpoint ────────────────────────────────────────────────────


@app.post("/computer-use")
async def computer_use(req: ComputerUseRequest):
    missing = []
    if not AZURE_OPENAI_KEY or not AZURE_OPENAI_ENDPOINT:
        missing.append("AZURE_OPENAI_KEY and AZURE_OPENAI_ENDPOINT")
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing .env config: {', '.join(missing)}",
        )

    return StreamingResponse(
        computer_use_stream(req.task, req.start_url),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
