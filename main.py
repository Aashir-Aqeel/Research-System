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
SCRAPE_CHAR_LIMIT = 6000

# How many results to scrape per sub-query
# Top 3 get full scrape, remainder fall back to snippet
SCRAPE_TOP_N = 3

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
    "twitter.com",
    "x.com",
    "instagram.com",
    "tiktok.com",
    "youtube.com",
    "reddit.com",
    "quora.com",
    "linkedin.com",
    "pinterest.com",
    "tumblr.com",
    "medium.com",
    "substack.com",
    "wordpress.com",
    "blogspot.com",
    "amazon.com",
    "ebay.com",
    "etsy.com",
    "alibaba.com",
    "yelp.com",
    "tripadvisor.com",
    "trustpilot.com",
    "ask.com",
    "answers.com",
    "ehow.com",
    "wikihow.com",
    "dailymail.co.uk",
    "thesun.co.uk",
    "nypost.com",
    "buzzfeed.com",
    "huffpost.com",
    "breitbart.com",
    "infowars.com",
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
    }


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

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(AZURE_CHAT_URL, headers=headers, json=body)
        resp.raise_for_status()

    return resp.json()["choices"][0]["message"]["content"]


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
    tier = classify_domain(result.get("url", ""))
    snippet = result.get("snippet", "")
    d = result.get("date", "")

    if tier == "blocked":
        return -1.0

    domain_score = {"tier1": 1.0, "tier2": 0.6, "unknown": 0.3}[tier]
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


async def enrich_result(result: dict, should_scrape: bool) -> dict:
    """
    Enrich a single result with full page content via Serper scrape.

    Strategy:
    - If should_scrape=True: try Serper scrape first
    - If scrape fails or should_scrape=False: fall back to snippet
    - Always sets: full_content, content_type, content_chars, tier
    """
    url = result.get("url", "")
    tier = classify_domain(url)

    if should_scrape:
        scraped = await serper_scrape(url)
        if scraped["success"] and scraped["chars"] > 200:
            result["full_content"] = scraped["text"]
            result["content_type"] = "full_page"
            result["content_chars"] = scraped["chars"]
        else:
            # Scrape failed — use snippet
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

    system = f"""You are a research planner. Today's date is {today}.

A user has a research question. Your job:
1. Think step by step about what information is needed to answer this comprehensively.
2. Break the question into 3-5 specific, targeted web search queries that together
   produce a complete and well-rounded answer.
3. For time-sensitive topics, include the current year ({date.today().year})
   or date range in relevant queries to get fresh results.
4. For legal/regulatory topics, include site-specific searches (e.g. site:leginfo.legislature.ca.gov)
   and cite specific bill/regulation numbers where known.

Respond ONLY with valid JSON — no markdown fences, no extra explanation:
{{
  "reasoning": "2-3 sentence explanation of your research strategy",
  "queries": [
    "specific search query 1",
    "specific search query 2",
    "specific search query 3"
  ]
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
    return json.loads(clean)


async def search_and_summarize(sub_query: str, index: int) -> dict:
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
    raw_results = await serper_search(sub_query, num=10)

    if not raw_results:
        return {
            "index": index,
            "query": sub_query,
            "summary": "No search results found for this query.",
            "citations": [],
        }

    # ── 3b: filter + rank ────────────────────────────────────────────────────
    ranked = filter_and_rank(raw_results, top_n=6)

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
    system = f"""You are a senior research analyst with access to web content \
from quality-filtered, ranked sources.

Content breakdown for this query:
- {full_count} sources with FULL PAGE content (scraped via Serper)
- {snippet_count} sources with snippet-only content

Instructions:
- Synthesize key facts, figures, dates, and insights into 2-4 focused paragraphs
- Heavily prioritize information from full-page sources over snippet-only sources
- Be specific: include exact numbers, dates, names, and legislation/paper references
- Flag claims that appear in only ONE source as "(reported by one source)"
- Flag claims that appear in 3+ sources as well-established
- Do NOT add any information not present in the provided content
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

You have {len(search_results)} research summaries, drawn from {total_sources} sources \
across {len(search_results)} targeted sub-queries. {total_full} of those sources were \
read in full (not just snippets).

Synthesize everything into a single, authoritative, comprehensive answer.

Rules:
- Write in clear flowing prose — paragraphs, not bullet points or headers
- Do NOT just concatenate the summaries — genuinely synthesize and cross-reference them
- Lead with the most important finding, then build supporting context
- Be specific: exact numbers, dates, bill numbers, names, citations
- Where sources agree, state it confidently
- Where sources conflict or a claim is single-sourced, flag it explicitly
- Close with a brief assessment of confidence level based on source quality and agreement
- Aim for 450-650 words"""

    context = "\n\n".join(
        f'=== Sub-research: "{r["query"]}" ===\n{r["summary"]}' for r in search_results
    )

    return await call_azure(
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

        tasks = [search_and_summarize(q, i) for i, q in enumerate(decomp["queries"])]

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
        f"=== Round {s['round']}, Query: \"{s['query']}\" ===\n{s['summary']}"
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

CONFIDENCE SCORE RUBRIC — use this calibration table strictly:
- 0.90-1.00: All requested data found from primary/Tier-1 sources. No material gaps.
             Multiple independent sources agree. Specific numbers, dates, names confirmed.
- 0.80-0.89: Most requested data found. Minor gaps remain (e.g. one sub-question weaker).
             At least 2-3 good sources per major claim. Some Tier-2 sources acceptable.
- 0.70-0.79: Core answer is there but significant gaps remain. Several claims from
             single sources only. Key data points (prices, scores, dates) unverified.
- 0.60-0.69: Major portions of the question unanswered. Primary sources not found.
             Mostly secondary/indirect evidence. Significant uncertainty in conclusions.
- 0.50-0.59: Question cannot be well answered from available evidence. Critical data
             missing (paywalled, not indexed, too recent, or doesn't exist publicly).
- 0.30-0.49: Almost no verifiable evidence found. Claims are speculative or inferred.
- 0.00-0.29: No reliable evidence found. Cannot answer the question from public sources.

CRITICAL: Do NOT anchor to 0.75-0.80 as a default. Use the rubric above honestly.
If primary sources were paywalled or missing, score below 0.65.
If the user asked for specific data (prices, clinical results, scores) that was not found, score below 0.70.
If all major questions are answered with good sources, score above 0.85.

Rules for follow_up_queries:
- Maximum {MEDIUM_QUERIES_PER_ROUND} queries
- Each must target a SPECIFIC gap not already covered
- Must be meaningfully different from already-searched queries
- If confidence >= 0.85 or no real gaps exist, set gaps_found=false and follow_up_queries=[]
- Focus on: missing data points, unverified claims, unexplored angles, conflicting info"""

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

    clean = raw.replace("```json", "").replace("```", "").strip()
    data = json.loads(clean)

    # Safety: ensure follow_up_queries is always a list
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
        rounds_context += f"\n--- Query: \"{s['query']}\" ---\n{s['summary']}\n"

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

    system = f"""You are a world-class research analyst producing a comprehensive research report.

Research statistics:
- Rounds completed: {rounds_completed}
- Total sources analyzed: {total_sources}
- Full pages read: {total_scraped}
- High-authority (Tier 1) sources: {tier1_count}

Produce a STRUCTURED RESEARCH REPORT with these exact sections:

## Executive Summary
2-3 sentences capturing the most important finding and overall confidence level.

## Key Findings
3-6 major findings, each as a short paragraph. For each finding state:
- The finding itself (specific, with numbers/dates where available)
- Source confidence: how many sources support it and their quality
- Any caveats or conditions

## Detailed Analysis
3-4 paragraphs of deep analysis synthesizing across all rounds.
Cross-reference findings. Build a coherent narrative. Do NOT just list facts.
This is where you show the relationships, patterns, and implications.

## Conflicting Information & Uncertainties
What do sources disagree on? What could not be verified?
What single-source claims need caution? What remains unknown?

## Confidence Assessment
Overall confidence score (Low / Medium / High / Very High) with reasoning.
What would increase confidence further?

Rules:
- Be specific: exact numbers, dates, names, bill numbers, paper titles
- Cite source quality inline e.g. "(confirmed by 3 Tier-1 sources)"
- Flag single-source claims as "[single source]"
- Aim for 900-1300 words total
- Use ## headers exactly as shown above
- Write for an intelligent professional audience{table_note}"""

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

                decomp = await decompose_query(query)
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
                search_and_summarize(q, i) for i, q in enumerate(queries_this_round)
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

                # Stop early if confidence is high enough after min rounds
                if has_min_rounds and not gap["gaps_found"]:
                    yield sse(
                        "early_stop",
                        {
                            "round": round_num,
                            "reason": "Research sufficiently complete",
                            "confidence": gap.get("confidence", 0),
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

        report = await synthesize_report(
            query,
            all_summaries,
            all_citations,
            rounds_completed,
            gap_analyses,
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
        rounds_context += f"\n--- Query: \"{s['query']}\" ---\n{s['summary']}\n"

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

    # Detect if the user explicitly requested a comparison table
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
    query_lower = original_query.lower()
    wants_table = any(kw in query_lower for kw in table_keywords)

    table_instruction = ""
    if wants_table:
        table_instruction = """

IMPORTANT: The user explicitly requested a comparison table. You MUST include it.
Add a section ## Comparison Table immediately after Key Findings.
Use proper markdown table syntax:
| Feature | Option A | Option B |
|---|---|---|
| Row 1 | ... | ... |
Populate every cell with specific, concrete values from your research.
If data is unavailable for a cell, write "Not publicly documented" — never leave cells empty."""

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

Rules:
- Minimum 1500 words, target 2000 words
- Be specific: exact figures, dates, legislation numbers, paper titles
- Cite source quality inline: "(3 Tier-1 sources)", "(single source — treat with caution)"
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
                gap = await analyze_gaps(query, round_num, all_summaries, seen_queries)
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

                if has_min and not gap["gaps_found"]:
                    yield sse(
                        "early_stop",
                        {
                            "round": round_num,
                            "reason": "Research sufficiently complete",
                            "confidence": gap.get("confidence", 0),
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

    system = f"""You are a deep research planner. Today's date is {today}.

A user has a research question requiring thorough investigation. Your job:
1. Think carefully about ALL information dimensions needed for a complete answer.
2. Generate 4-6 specific, targeted web search queries covering different angles.
3. Each query must target a DIFFERENT aspect — do not repeat similar queries.
   Vary between: primary sources, secondary analysis, specific data points, regional sources.
{benchmark_instruction}{pakistan_instruction}

CRITICAL RULES:
- Never generate generic queries like "Samsung S26 Ultra review" — be specific
- Include the current year (2026) or month (April 2026) in time-sensitive queries
- For pricing queries, name the specific city/country and include "open market"
- For benchmarks, name the specific test platform (DXOMARK, GSMArena, AnTuTu, etc.)
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

    clean = raw.replace("```json", "").replace("```", "").strip()
    result = json.loads(clean)

    # Post-process: enrich with Pakistan-specific queries if needed
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
    raw_results = await serper_search(sub_query, num=10)

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

    system = f"""You are a senior research analyst. You have deep web content from
quality-filtered, ranked, relevance-checked sources for a specific query.

Content breakdown:
- {browser_count} sources read via real browser (Playwright — highest depth)
- {full_count - browser_count} sources scraped via Serper
- {snippet_count} sources with snippet only
- All browser/scraped content has passed a relevance filter for this query

Instructions:
- Synthesize key facts, figures, dates, and insights into 2-4 focused paragraphs
- Heavily prioritize browser-fetched content (marked ★ DIRECT = primary source)
- Be specific: exact numbers, dates, names, PKR prices, benchmark scores
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
                decomp = await decompose_query_deep(query)
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
                gap = await analyze_gaps(query, round_num, all_summaries, seen_queries)
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

                if has_min and not gap["gaps_found"]:
                    yield sse(
                        "early_stop",
                        {
                            "round": round_num,
                            "reason": "Research sufficiently complete",
                            "confidence": gap.get("confidence", 0),
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
