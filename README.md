# GhostWriter

> Automated Ghost CMS blog article generator. Connects to any OpenAI-compatible LLM to research topics, write SEO-optimized articles, and publish them to your Ghost blog.

## Quick Start

```bash
git clone https://github.com/wyatts97/GhostWriter.git
cd GhostWriter

# Configure your environment
cp .env.example .env
# Edit .env with your Ghost URL, Admin API Key, and LLM API key

# Build and run
docker compose up -d
```

Open **http://localhost:3639** to access the GhostWriter dashboard.

## How It Works

GhostWriter is a single Docker container (FastAPI + APScheduler) that connects three things:

1. **Your Ghost blog** (already running separately) via the [Admin API](https://docs.ghost.org/admin-api)
2. **An LLM provider** — any OpenAI-compatible API (OpenAI, Claude, Deepseek, Gemini, etc.)
3. **RSS feeds** — news sources that provide context for article generation

The web UI at port `3639` lets you configure everything:

- **Prompts** — system prompts that define the LLM's tone, style, and structure
- **RSS Feeds** — add news publications to use as source material
- **Schedules** — cron-based automation: pick a prompt, select feeds, set frequency
- **Settings** — LLM provider, Ghost connection, global config
- **Articles** — view, publish, regenerate, or delete generated content

## Features

- **Draft or Publish** — each schedule can save articles as Ghost drafts or publish immediately
- **Any LLM** — works with OpenAI, Anthropic Claude, Deepseek, Google Gemini, or any OpenAI-compatible endpoint
- **SEO Optimized** — auto-generated meta titles, descriptions, OG tags, Twitter cards, heading hierarchy
- **Structured Output** — LLM generates JSON with all fields parsed and validated
- **RSS Context** — pulls the latest entries from your configured feeds for each article
- **Scheduling** — cron expressions for fully automated content pipelines
- **Dark/Light UI** — Revolut-inspired design system with high-contrast canvas modes

## Configuration

### Environment Variables (`.env`)

| Variable | Description |
|----------|-------------|
| `GHOST_ADMIN_URL` | Your Ghost blog URL (e.g., `https://yourblog.ghost.io`) |
| `GHOST_ADMIN_API_KEY` | Admin API Key from Ghost Integrations |
| `LLM_API_BASE` | OpenAI-compatible API base URL (default: `https://api.openai.com/v1`) |
| `LLM_API_KEY` | Your LLM API key |
| `LLM_DEFAULT_MODEL` | Default model (e.g., `gpt-4o`, `claude-sonnet-4-20250514`) |
| `APP_SECRET_KEY` | Random secret for API key encryption |

### Getting a Ghost Admin API Key

1. Go to your Ghost Admin panel → **Settings** → **Integrations**
2. Click **"Add custom integration"** and name it "GhostWriter"
3. Copy the **Admin API Key** — this is your `GHOST_ADMIN_API_KEY`

### Supported LLM Providers

GhostWriter uses the OpenAI-compatible `/v1/chat/completions` format:

| Provider | Base URL | Notes |
|----------|----------|-------|
| **OpenAI** | `https://api.openai.com/v1` | gpt-4o, gpt-4o-mini |
| **Anthropic** | `https://api.anthropic.com/v1` | Claude Sonnet 4, Claude Haiku 3.5 |
| **Deepseek** | `https://api.deepseek.com/v1` | deepseek-chat |
| **Google Gemini** | `https://generativelanguage.googleapis.com/v1beta/openai/` | gemini-2.0-flash |

## Usage Flow

1. **Add RSS feeds** — go to **Feeds**, add news sources relevant to your blog topics
2. **Create a prompt** — go to **Prompts**, write a system prompt that defines the article style
3. **Set up a schedule** — go to **Schedules**, link a prompt + feeds, set frequency and publish mode
4. **Let it run** — GhostWriter will automatically fetch feeds, generate articles, and send them to Ghost
5. **Review articles** — go to **Articles** to view, publish drafts, or regenerate

## Tech Stack

- **Python 3.12** + **FastAPI** — async web framework
- **Jinja2** — server-rendered templates
- **SQLite** — zero-config database (persisted via Docker volume)
- **APScheduler** — cron-based job scheduling
- **httpx** — async HTTP client for LLM and Ghost APIs
- **feedparser** — RSS/Atom feed parsing
- **Revolut Design System** — dark/light high-contrast UI

## Project Structure

```
ghostwriter/
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── requirements.txt
├── app/
│   ├── main.py                 # FastAPI app entry point
│   ├── config.py               # Pydantic settings
│   ├── database.py             # SQLAlchemy async engine
│   ├── models/                  # Database models (6 tables)
│   ├── routers/                 # Route handlers (6 modules)
│   ├── services/                # Business logic (5 modules)
│   ├── utils/                   # SEO helpers
│   ├── static/css/              # Design tokens + component CSS
│   └── templates/               # Jinja2 templates (13 files)
└── data/                        # SQLite database (mounted volume)
```

## License

MIT
