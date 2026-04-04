# Central Research System — Light Research

A local research engine powered by OpenAI GPT-4o with web search.

## Stack

- **Backend**: Python + FastAPI (async)
- **Frontend**: Plain HTML/CSS/JS (no build step)
- **AI**: OpenAI Responses API with `web_search_preview`
- **Streaming**: Server-Sent Events (SSE)

## How the pipeline works

```
Your question
    │
    ▼
[Step 1+2] GPT-4o reasons about your question and breaks it into 3–5 sub-queries
    │
    ▼
[Step 3]   All sub-queries fire in PARALLEL via asyncio.as_completed()
           Each one uses OpenAI's built-in web_search_preview tool
    │
    ▼
[Step 4]   GPT-4o synthesizes all results into one coherent answer
    │
    ▼
Final answer with cited sources
```

---

## Setup

### 1. Clone / copy this folder to your machine

### 2. Create a virtual environment

```bash
cd research_system
python -m venv venv

# Activate it:
# macOS / Linux:
source venv/bin/activate

# Windows:
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. (Optional) Set your API key via .env

```bash
cp .env.example .env
# Edit .env and paste your OpenAI API key
```

> You can also just type the key directly in the browser UI — it is never stored.

### 5. Run the server

```bash
python main.py
```

Or with uvicorn directly:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 6. Open the app

Visit: http://localhost:8000

---

## Project structure

```
research_system/
├── main.py              ← FastAPI backend (all research logic)
├── requirements.txt     ← Python dependencies
├── .env.example         ← Copy to .env and add your API key
├── README.md
└── static/
    └── index.html       ← Frontend (single file, no build needed)
```

---

## Requirements

- Python 3.11+
- An OpenAI API key with access to `gpt-4o` and `web_search_preview`
  (web_search_preview requires a paid OpenAI account)

---

## Next steps (planned modes)

| Mode         | Description                                             |
| ------------ | ------------------------------------------------------- |
| Medium       | Recursive light research with gap detection (3–5 loops) |
| Deep         | Higher loop cap + full browser navigation               |
| Computer Use | Playwright agent for interactive web automation         |
