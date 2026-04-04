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

    port = int(os.getenv("PORT", 7860))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
