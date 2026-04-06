---
title: Research System
emoji: 🔬
colorFrom: green
colorTo: blue
sdk: docker
pinned: false
---

# Central Research System — by Ragioneer

A self-hosted research engine that thinks before it searches. Built on **Azure OpenAI + Serper + Playwright**, it runs recursive multi-round research pipelines and produces structured, cited reports.

> **Live demo:** [aashir-aqeel-research-system.hf.space](https://aashir-aqeel-research-system.hf.space)

---

## Research Modes

| Mode       | Rounds  | Browser       | Academic       | Output                           |
| ---------- | ------- | ------------- | -------------- | -------------------------------- |
| **Light**  | 1 pass  | —             | —              | 400–600 word answer              |
| **Medium** | Up to 4 | —             | —              | 900–1300 word structured report  |
| **Deep**   | Up to 8 | ✅ Playwright | ✅ auto-detect | 1500–2500 word report + download |

---

## How the Pipeline Works

```
Your question
      │
      ▼
[Steps 1+2]  Azure GPT reasons and breaks into 3–6 targeted sub-queries
      │
      ▼
[Step 3]     All sub-queries fire in PARALLEL
             ├── Serper Search  → 10 real Google results per query
             ├── Source filter  → blocked domains removed, scored by
             │                    authority tier + recency + quality
             ├── Serper Scrape  → top results get full page content
             │                    (headless browser via Serper API)
             └── [Deep only]    → Playwright browser for JS-heavy pages
                                   + arXiv/Semantic Scholar for academic queries
      │
      ▼
[Step 4]     Azure GPT synthesizes into a structured answer/report
             with confidence assessment, source flagging, and optional
             comparison tables
      │
      ▼  [Medium/Deep only — repeat with gap detection]
[Gap Analysis]  GPT evaluates what's missing → generates follow-up queries
             → loops back to Step 3 until confidence ≥ 85% or max rounds
```

Everything streams to the browser in real time via **Server-Sent Events**.

---

## Key Features

- **Source quality scoring** — 80+ Tier 1 domains (academic, government, major press), blocked list for SEO farms and social media
- **Full page scraping** — Serper's headless browser reads real article content, not 2-line snippets
- **Playwright browser** (Deep mode) — handles JS-rendered pages, bot detection, government databases
- **Academic search** — arXiv + Semantic Scholar APIs for scientific queries (auto-detected)
- **Confidence calibration** — calibrated rubric prevents the common LLM anchor to 0.75-0.80
- **Strategy pivots** — gap analysis detects when an approach is failing and switches strategy
- **Comparison table detection** — honors explicit table requests in synthesis
- **Pakistan pricing awareness** — auto-injects PSEB, PriceOye, Hamariweb for local queries
- **Epistemic honesty** — single-source claims flagged, conflicting info noted, paywalls acknowledged
- **Downloadable reports** — Deep Research exports full markdown with citations
- **Ragioneer-branded UI** — dark theme, Syne typography, real-time pipeline visualization

---

## Stack

| Layer     | Technology                                            |
| --------- | ----------------------------------------------------- |
| Backend   | Python 3.11+ · FastAPI · asyncio                      |
| LLM       | Azure OpenAI GPT-4o (Chat Completions API)            |
| Search    | Serper — Google Search API                            |
| Scraping  | Serper `/scrape` — headless browser                   |
| Browser   | Playwright (Chromium, sync API in ThreadPoolExecutor) |
| Academic  | arXiv API + Semantic Scholar API (free, no key)       |
| Streaming | Server-Sent Events (SSE)                              |
| Frontend  | Vanilla HTML/CSS/JS — no build step                   |

---

## Setup

### 1. Clone

```bash
git clone https://github.com/Aashir-Aqeel/Research-System.git
cd Research-System
```

### 2. Virtual environment

```bash
python -m venv venv
source venv/bin/activate      # macOS/Linux
venv\Scripts\activate         # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 4. Configure `.env`

```bash
cp .env.example .env
```

Fill in:

```env
AZURE_OPENAI_KEY=your-azure-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2024-08-01-preview
SERPER_API_KEY=your-serper-key
BROWSER_HEADLESS=true
```

**Where to find these:**

- Azure key + endpoint → Azure Portal → your OpenAI resource → Keys and Endpoint
- Deployment name → Azure OpenAI Studio → Deployments
- Serper key → [serper.dev](https://serper.dev) (free tier: 2,500 searches/month)

### 5. Run

```bash
python main.py
```

Open: `http://localhost:8000`

---

## Project Structure

```
Research-System/
├── main.py              ← FastAPI backend — all pipeline logic (3,100+ lines)
├── requirements.txt     ← 5 dependencies
├── .env.example         ← Copy to .env
├── Dockerfile           ← For HF Spaces / Docker deployment
├── README.md
└── static/
    └── index.html       ← Frontend — single file, no build needed
```

---

## Roadmap

| Mode                            | Status  |
| ------------------------------- | ------- |
| Light Research                  | ✅ Live |
| Medium Research                 | ✅ Live |
| Deep Research                   | ✅ Live |
| Computer Use (Playwright agent) | 🔨 Next |

---

## Cost Per Query (Approximate)

| Mode   | Azure tokens | Serper credits         | Time      |
| ------ | ------------ | ---------------------- | --------- |
| Light  | ~24,000      | 5 search + 15 scrape   | ~30s      |
| Medium | ~80,000      | 20 search + 60 scrape  | ~2-3 min  |
| Deep   | ~200,000     | 40 search + 120 scrape | ~5-15 min |

---

Built by [Ragioneer](https://ragioneer.com) — Mission-Driven AI Systems
