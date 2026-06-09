# GhostWriter — Architecture & Execution Plan

## 1. System Overview

GhostWriter is a **single Docker container** (FastAPI + APScheduler) that connects to:

- **A Ghost blog** (running separately) via Admin API → creates/publishes articles
- **OpenAI-compatible LLM APIs** (OpenAI, Claude, Deepseek, Gemini, etc.) → generates articles
- **External RSS feeds** → fetches news/topics for article context

The web UI (port 3639) is a **server-rendered Jinja2 interface** styled after the Revolut design system in DESIGN.MD — a dark/light high-contrast two-mode system with pill-shaped buttons, Inter typography, and cobalt violet accents.

### High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    Docker Container                              │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  FastAPI Uvicorn Server (port 3639)                    │     │
│  │                                                        │     │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────┐   │     │
│  │  │  Web UI      │  │  Admin API   │  │Background  │   │     │
│  │  │  (Jinja2)    │  │  (REST)      │  │Scheduler   │   │     │
│  │  └──────┬───────┘  └──────┬───────┘  │(APScheduler│   │     │
│  │         │                  │          └─────┬──────┘   │     │
│  │         │                  │                │          │     │
│  │  ┌──────▼──────────────────▼────────────────▼──────┐   │     │
│  │  │              Service Layer                       │   │     │
│  │  │  ┌──────────┐ ┌──────────┐ ┌────────────────┐   │   │     │
│  │  │  │ LLM Client│ │   Ghost  │ │  Article Gen   │   │   │     │
│  │  │  │(OpenAI)   │ │  Client  │ │  Engine        │   │   │     │
│  │  │  └──────────┘ └──────────┘ └────────────────┘   │   │     │
│  │  │  ┌──────────┐ ┌──────────┐                      │   │     │
│  │  │  │ RSS Feed │ │  SEO     │                      │   │     │
│  │  │  │ Fetcher  │ │  Utils   │                      │   │     │
│  │  │  └──────────┘ └──────────┘                      │   │     │
│  │  └─────────────────────────────────────────────────┘   │     │
│  │                                                        │     │
│  │  ┌─────────────────────────────────────────────────┐   │     │
│  │  │              SQLite Database                     │   │     │
│  │  │  /data/ghostwriter.db (mounted volume)          │   │     │
│  │  └─────────────────────────────────────────────────┘   │     │
│  └────────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────┘
         │                          │
         │ HTTPS                    │ HTTPS
         ▼                          ▼
┌──────────────────┐    ┌──────────────────────┐
│   Ghost Blog     │    │  LLM Provider        │
│   Admin API      │    │  /v1/chat/completions│
│   *.ghost.io     │    │  (OpenAI/Claude/     │
│                  │    │   Deepseek/Gemini)    │
└──────────────────┘    └──────────────────────┘
```

---

## 2. Implementation Phases

| Phase | Description | Est. Files |
|-------|-------------|------------|
| **P1** | Foundation — Docker, FastAPI scaffold, DB models, config | 10 |
| **P2** | Services — LLM client, Ghost client, RSS fetcher, article engine | 6 |
| **P3** | Web UI — All pages with Revolut design | 15+ |
| **P4** | Automation — Scheduler, article pipeline, error handling | 4 |
| **P5** | Polish — SEO, edge cases, production hardening, QA | 5 |

---

## 3. Phase 1: Foundation

### 3.1 Project Structure

```
ghostwriter/
├── docker-compose.yml
├── Dockerfile
├── .env                         # GHOST_URL, GHOST_ADMIN_KEY, OPENAI_API_KEY, etc
├── requirements.txt
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app, lifespan, router mounts
│   ├── config.py                # Pydantic Settings from env vars + DB settings
│   ├── database.py              # SQLAlchemy async engine + session factory
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py              # SQLAlchemy Base + mixins
│   │   ├── settings.py          # LLM config, Ghost config
│   │   ├── rss.py               # RSS feed sources + fetched entries
│   │   ├── prompts.py           # System prompts for LLM
│   │   ├── schedules.py         # Cron schedules
│   │   └── articles.py          # Generated articles
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── dashboard.py         # GET / — stats overview
│   │   ├── prompts.py           # CRUD for prompts
│   │   ├── feeds.py             # CRUD for RSS feeds
│   │   ├── settings.py          # LLM + Ghost settings
│   │   ├── articles.py          # Article history + manual trigger
│   │   └── schedules.py         # CRUD for schedules
│   ├── services/
│   │   ├── __init__.py
│   │   ├── llm_client.py        # OpenAI-compatible client wrapper
│   │   ├── ghost_client.py      # Ghost Admin API client
│   │   ├── rss_fetcher.py       # RSS feed polling + parsing
│   │   ├── article_generator.py # Assemble context → LLM → structured article
│   │   └── scheduler.py         # APScheduler integration
│   ├── static/
│   │   ├── css/
│   │   │   ├── tokens.css       # Design tokens as CSS custom properties
│   │   │   └── main.css         # All component styles
│   │   ├── js/
│   │   │   └── app.js           # Minimal JS for interactivity
│   │   └── fonts/               # Inter (subset for self-hosting)
│   ├── templates/
│   │   ├── base.html           # Base layout shell
│   │   ├── components/         # Reusable UI components
│   │   │   ├── button.html
│   │   │   ├── card.html
│   │   │   ├── input.html
│   │   │   ├── badge.html
│   │   │   ├── pill.html
│   │   │   ├── table.html
│   │   │   └── modal.html
│   │   ├── dashboard.html
│   │   ├── feeds/
│   │   │   ├── list.html
│   │   │   └── form.html
│   │   ├── prompts/
│   │   │   ├── list.html
│   │   │   └── form.html
│   │   ├── settings.html
│   │   ├── schedules/
│   │   │   ├── list.html
│   │   │   └── form.html
│   │   └── articles/
│   │       ├── list.html
│   │       └── detail.html
│   └── utils/
│       ├── __init__.py
│       └── seo.py               # SEO helpers (meta, slug, keyword extraction)
├── data/                        # Mounted volume
│   └── ghostwriter.db
└── .dockerignore
```

### 3.2 Docker Setup

**Dockerfile** — single-stage, production-focused:
- `python:3.12-slim` base
- Install system deps: `libsqlite3-0`, `curl` (healthcheck)
- `pip install -r requirements.txt`
- Copy `app/` directory
- `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3639"]`
- Healthcheck: `curl -f http://localhost:3639/health`

**docker-compose.yml:**
- Single service: `ghostwriter`
- Build from Dockerfile
- Port mapping: `3639:3639`
- Volume: `./data:/app/data` for SQLite persistence
- Environment variables from `.env` file
- Restart policy: `unless-stopped`

### 3.3 Database Models (SQLAlchemy ORM)

```python
# Core tables:

settings:
  id, key (unique), value (text)       # Key-value store for all config

rss_feeds:
  id, name, url, topic (str), active (bool), 
  fetch_interval_minutes (int), last_fetched_at (datetime|null),
  created_at, updated_at

feed_entries:
  id, feed_id (FK), title, url (unique per feed), 
  content (text), summary (text), published_at (datetime),
  fetched_at (datetime), is_used (bool)  # Track if consumed by article gen

prompts:
  id, name, content (text), model_override (str|null),
  temperature (float, default 0.7), max_tokens (int, default 4000),
  created_at, updated_at

schedules:
  id, name, cron_expression (str), prompt_id (FK),
  feed_ids (JSON — list of FK), active (bool),
  publish_mode (enum: draft, publish — default: draft),
  max_articles_per_run (int, default 1),
  created_at, updated_at

generated_articles:
  id, prompt_id (FK), feed_entry_ids (JSON), title, 
  content (text), excerpt (text), feature_image_url (str|null),
  tags (JSON), seo_title (str|null), seo_description (str|null),
  og_image (str|null), og_title (str|null), og_description (str|null),
  twitter_image (str|null), twitter_title (str|null), twitter_description (str|null),
  ghost_post_id (str|null), ghost_url (str|null),
  status (enum: draft, draft_sent, published, failed, skipped),
  error_message (text|null), scheduled_at (datetime|null),
  created_at, updated_at
```

### 3.4 Config & Environment Variables

```env
# .env
GHOST_ADMIN_URL=https://yourblog.ghost.io
GHOST_ADMIN_API_KEY=your_admin_api_key

# LLM Provider
LLM_API_BASE=https://api.openai.com/v1   # or https://api.anthropic.com/v1, etc
LLM_API_KEY=sk-...
LLM_DEFAULT_MODEL=gpt-4o                 # or claude-sonnet-4-20250514, etc

# App
APP_SECRET_KEY=random-secret-for-sessions
LOG_LEVEL=info
```

`config.py` uses `pydantic-settings` to load from env with sensible defaults. The web UI can override runtime settings (stored in `settings` table).

---

## 4. Phase 2: Core Services

### 4.1 LLM Client (`services/llm_client.py`)

**Purpose**: Unified interface to any OpenAI-compatible chat completion API.

- **Base URL**: Configurable (`LLM_API_BASE`), defaults to `https://api.openai.com/v1`
- **Compatible providers**: OpenAI, Anthropic (via `/v1` proxy), Deepseek, Google Gemini (via OpenAI-compat endpoint), any local proxy
- **API**: `async def generate_chat(messages: list, model: str, temperature: float, max_tokens: int, response_format: dict | None) -> dict`
- **Structured output**: Use `response_format={"type": "json_object"}` or function calling for consistent article structure
- **Retry**: Exponential backoff (3 attempts) on 429, 500, 503
- **Streaming**: Optional for live preview
- **Token tracking**: Log prompt + completion tokens per call

**Article generation schema** (via structured output):

```python
article_schema = {
    "type": "json_object",
    "schema": {
        "title": "string (SEO-optimized, under 70 chars)",
        "excerpt": "string (compelling summary, 150-160 chars)",
        "content": "string (full markdown article, 1500-2500 words)",
        "tags": "array of strings (relevant tags, 3-5)",
        "seo_title": "string (under 60 chars)",
        "seo_description": "string (under 160 chars)",
        "og_title": "string",
        "og_description": "string",
        "twitter_title": "string",
        "twitter_description": "string"
    }
}
```

### 4.2 Ghost Client (`services/ghost_client.py`)

**Purpose**: Create and publish articles via Ghost Admin API.

- **Auth flow**: JWT token generated from Admin API Key (admin-only)
  - Decode the key (split on `:` gives `id:secret`)
  - Sign JWT with `id` as `kid` header, `secret` as HMAC-SHA256
  - Token expires 5 minutes, generate per-request
- **Endpoints used**:
  - `POST /ghost/api/admin/posts/` — create post
  - `PUT /ghost/api/admin/posts/{id}/` — update post  
  - `GET /ghost/api/admin/posts/{id}/` — fetch post status
  - `GET /ghost/api/admin/tags/` — verify/sync tags
- **Post payload**:

```python
{
    "posts": [{
        "title": str,
        "custom_excerpt": str,
        "feature_image": str | None,
        "feature_image_alt": str | None,
        "feature_image_caption": str | None,
        "status": "draft" | "published",
        "visibility": "public",
        "tags": [{"name": tag} for tag in tags],
        "html": markdown_to_html(content),
        "meta_title": seo_title,
        "meta_description": seo_description,
        "og_image": og_image,
        "og_title": og_title,
        "og_description": og_description,
        "twitter_image": twitter_image,
        "twitter_title": twitter_title,
        "twitter_description": twitter_description,
        "codeinjection_head": "<script>...</script>" | None,  # optional tracking
        "codeinjection_foot": "<script>...</script>" | None
    }]
}
```

- **Feature images**: Optionally use Unsplash or Pexels API integration to auto-attach relevant images
- **Error handling**: Detect 401 (key invalid), 422 (validation), 429 (rate limit)

### 4.3 RSS Fetcher (`services/rss_fetcher.py`)

**Purpose**: Poll RSS feed URLs, parse entries, store in DB.

- **Library**: `feedparser` (battle-tested, handles RSS 2.0, Atom, RDF)
- **HTTP**: `httpx` with 30s timeout, user-agent header
- **Deduplication**: Unique by `(feed_id, entry_url)` — skip if already fetched
- **Content extraction**: 
  - Use `entry.content[0].value` or `entry.summary` if available
  - Fall back to fetching the article URL and extracting with `readability-lxml` or `trafilatura`
- **Automatic cleanup**: Purge entries older than 30 days
- **Per-feed scheduling**: Each feed has its own `fetch_interval_minutes` (default 60)

### 4.4 Article Generator (`services/article_generator.py`)

**Purpose**: Assemble context from RSS feeds + prompts → call LLM → parse structured output.

**Pipeline**:
1. **Collect source material**: For a given schedule run, get recent/random entries from associated feeds
2. **Build context**: Summarize each source into digestible form (title + key points)
3. **Assemble system prompt**: 
   ```
   System: {prompt.content}
   
   Today's date: {current_date}
   
   Source material for this article:
   {formatted_sources}
   ```
4. **Call LLM**: With structured output schema
5. **Parse response**: Validate all required fields, fallback on missing
6. **Post-process**:
   - Convert markdown to HTML for Ghost
   - Extract/validate SEO fields
   - Generate slug if not provided
7. **Save to DB**: As `generated_articles` with status "draft"

**SEO optimization baked in**:
- Title auto-optimization (70 char limit, keyword front-loading)
- Meta description generation (150-160 char, CTA included)
- Header hierarchy checks (h1 → h2 → h3)
- Internal link suggestions (future)
- Keyword density guidance in system prompt

---

## 5. Phase 3: Web UI (Revolut Design)

### 5.1 Design Token Implementation

Map every DESIGN.MD token to CSS custom properties in `tokens.css`:

```css
:root {
  /* Brand & Accent */
  --color-primary: #494fdf;
  --color-primary-bright: #4f55f1;
  --color-primary-deep: #3a40c4;
  --color-on-primary: #ffffff;

  /* Canvas */
  --color-canvas-light: #ffffff;
  --color-canvas-dark: #000000;
  --color-surface-soft: #f4f4f4;
  --color-surface-card: #ffffff;
  --color-surface-deep: #0a0a0a;
  --color-surface-elevated: #16181a;

  /* Borders */
  --color-hairline-light: #e2e2e7;
  --color-hairline-dark: rgba(255,255,255,0.12);
  --color-hairline-strong: #191c1f;

  /* Text */
  --color-ink: #191c1f;
  --color-body: #1f2226;
  --color-charcoal: #3a3d40;
  --color-mute: #505a63;
  --color-ash: #5c5e60;
  --color-stone: #8d969e;
  --color-faint: #c9c9cd;
  --color-on-dark: #ffffff;
  --color-on-dark-mute: rgba(255,255,255,0.72);

  /* Semantic */
  --color-accent-teal: #00a87e;
  --color-accent-light-blue: #007bc2;
  --color-accent-blue-link: #376cd5;
  --color-accent-green-text: #006400;
  --color-accent-warning: #ec7e00;
  --color-accent-pink: #e61e49;
  --color-accent-danger: #e23b4a;
  --color-accent-deep-red: #8b0000;

  /* Typography */
  --font-display: 'Inter', 'General Sans', system-ui, sans-serif;
  --font-body: 'Inter', system-ui, sans-serif;

  /* Spacing (4px base) */
  --spacing-xxs: 4px;
  --spacing-xs: 6px;
  --spacing-sm: 8px;
  --spacing-md: 14px;
  --spacing-lg: 16px;
  --spacing-xl: 24px;
  --spacing-xxl: 32px;
  --spacing-xxxl: 48px;
  --spacing-block: 80px;
  --spacing-section: 88px;
  --spacing-band: 120px;

  /* Border Radius */
  --radius-none: 0px;
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 20px;
  --radius-xl: 28px;
  --radius-full: 9999px;
}
```

### 5.2 Page Architecture

The web UI has **two-mode canvas switching** per the design system:
- **Dark canvas** (`var(--color-canvas-dark) #000000`) for the main dashboard, hero sections
- **Light canvas** (`var(--color-canvas-light) #ffffff`) for data-heavy pages: table views, forms, settings

**Pages:**

| Route | Canvas Mode | Purpose |
|-------|-------------|---------|
| `/` | Dark | Dashboard — stats cards, recent articles, next scheduled run |
| `/prompts` | Dark → Light | Prompt library — list/create/edit prompts for LLM |
| `/feeds` | Dark → Light | RSS feed management — add/edit/remove feeds, test fetch |
| `/settings` | Light | LLM config, Ghost connection, global settings |
| `/schedules` | Dark → Light | Schedule management — cron config, prompt+feed assignment |
| `/articles` | Dark → Light | Article history — status filter, retry failed, view/publish |
| `/articles/{id}` | Light | Article detail — full content, SEO preview, publish button |

**Nav bar** (always dark canvas):
- Left: "GhostWriter" wordmark (Inter, weight 600)
- Centre: nav pills — Dashboard, Prompts, Feeds, Schedules, Articles
- Right: Settings gear icon + status indicator (online/offline)

### 5.3 Component Library

Reusable Jinja2 macros in `templates/components/`:

- `button.html` — `.button-primary` (white pill on dark), `.button-dark` (dark on light), `.button-soft`, `.button-outline-light`, `.button-outline-dark`, `.button-pill-sm`
- `card.html` — `.feature-card-light`, `.feature-card-dark`, `.plan-card`, `.plan-card-featured`
- `input.html` — `.text-input` (56px tall, 12px radius), select, textarea
- `badge.html` — `.badge-tag`, `.badge-feature`
- `table.html` — Data tables with hairline borders, no shadows
- `modal.html` — Confirmation dialogs, compose overlays
- `pill.html` — `.sub-nav-pill` for tab-like navigation
- `toast.html` — Notification toasts (success, error, warning)

### 5.4 Key UI Screens Detailed

**Dashboard** (dark canvas):
- Top: "GhostWriter" heading (display-lg, weight 500, line-height 1.0)
- Stats row (feature-cards on `--surface-elevated`): 
  - Articles published today / this week
  - Active schedules count
  - RSS feeds tracked
  - Next article generation time
- Recent activity feed: last 10 generation events with status badges
- Quick-action pills: "Generate Now", "Test RSS Feeds", "Sync Ghost Tags"

**Prompt Editor** (light canvas):
- Left sidebar: prompt list (pill-nav style)
- Right: full editor with:
  - Name input (text-input)
  - Content textarea (monospace, full height)
  - Model override select (optional)
  - Temperature slider (0.0–1.0)
  - Max tokens input
  - Test button → opens a preview modal

**RSS Feed Manager** (light canvas):
- Table with: Name, URL (truncated), Topic, Interval, Status (active/paused), Last Fetch
- Add feed modal with: Name, URL, Topic tag, Fetch interval
- "Test Feed" button → fetches and shows 5 most recent entries
- Entry preview collapsible

**Schedule Config** (light canvas):
- Grid of schedule cards (`.plan-card`)
- Each card shows: cron expression, linked prompt name, linked feeds, status toggle
- "Create Schedule" button → form with:
  - Schedule name
  - Cron expression builder (dropdown presets: every hour, every 4h, daily, twice daily, custom)
  - Prompt selection (dropdown)
  - Feed selection (multi-select pills)
  - Max articles per run
  - Publish mode toggle: "Save as Draft" vs "Publish Immediately" (pill-switch UI, default: draft)

**Settings** (light canvas, single-page):
- **LLM Provider** section: API Base URL, API Key (masked), Default Model
- **Ghost Integration** section: Admin URL, Admin API Key (masked), "Test Connection" button
- **General** section: Timezone, Article date format, Log level
- All changes save instantly (auto-save or explicit save button)

**Article History** (light canvas):
- Filterable table: Status pills, Title, Prompt used, Source feed, Created, Actions
- Actions per row: View, Publish (if draft), Regenerate, Delete
- Bulk actions: Retry Failed, Publish All Drafts
- Status badges: Draft (badge-tag), Published (badge-feature, green), Failed (danger)

---

## 6. Phase 4: Automation

### 6.1 Scheduler (`services/scheduler.py`)

**Architecture**: APScheduler with `AsyncIOScheduler`

- **Triggers**: CronTrigger from user-defined cron expressions
- **Startup**: On FastAPI lifespan startup, load all active schedules from DB and add jobs
- **Job function**: `async def generate_article_job(schedule_id: int)`
  - Lock: Prevent duplicate execution (use SQLite lock or in-memory flag)
  - Fetch schedule config (prompt, feeds)
  - Get recent RSS entries from linked feeds
  - Call Article Generator
  - Save to DB
  - Call Ghost Client (publish or draft based on schedule config)
  - Update article status + log
  - On failure: mark as failed, log error, retry on next cycle
- **Dynamic**: When user creates/edits/deletes a schedule in UI → add/modify/remove the job in APScheduler in real-time
- **Persistence**: APScheduler uses SQLite job store (same DB) so schedules survive restarts

### 6.2 Application Lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await database.init()
    await scheduler.start()
    yield
    # Shutdown
    scheduler.shutdown()
```

### 6.3 Article Generation Flow (detailed)

```
1. Cron trigger fires
2. scheduler.py loads schedule + prompt -> feeds
3. rss_fetcher.py polls each feed for fresh entries
4. Select N most relevant entries (or random sample)
5. Build context digest from entries
6. Assemble messages: [system_prompt, user_context]
7. Call LLM client with structured output schema
8. Parse JSON response, validate fields
9. Run SEO post-processing
10. Save GeneratedArticle to DB (status=draft)
11. Apply publish_mode from schedule:
    a. GhostClient.create_post(status=publish_mode)  # "draft" or "published"
    b. If publish_mode="published":
       - Update article with ghost_post_id, ghost_url
       - Mark article status as "published"
    c. If publish_mode="draft":
       - Update article with ghost_post_id
       - Mark article status as "draft_sent" (sent to Ghost, awaiting manual publish)
12. Log completion (success/failure)
```

---

## 7. Phase 5: Polish & Hardening

### 7.1 SEO Optimization (`utils/seo.py`)

- **Title optimization**: Check character limits, keyword placement, remove quotes/special chars
- **Meta description**: Ensure 150-160 chars, includes primary keyword + call to action
- **Content structure**: Validate heading hierarchy (only one h1, proper h2→h3 nesting)
- **Internal linking**: Optional — search existing articles for relevant links
- **Image alt text**: Extract and validate alt attributes
- **Slug generation**: URL-safe, keyword-rich slugs

### 7.2 Error Handling & Resilience

| Error | Mitigation |
|-------|-----------|
| LLM API timeout | Retry 3x with backoff, then fail gracefully |
| LLM rate limit (429) | Exponential backoff, queue remaining jobs |
| LLM invalid response | Validate JSON schema, retry with stricter prompt |
| Ghost API 401 | Alert user (UI banner), pause schedules |
| Ghost API 429 | Backoff, reschedule |
| RSS feed down | Log warning, skip feed, continue with others |
| RSS parse error | Log with feed URL, skip malformed entries |
| DB locked (SQLite) | WAL mode, single writer, timeout retry |
| Container restart | APScheduler persists jobs to SQLite |

### 7.3 Security

- Admin API Key stored in DB (encrypted at rest with fernet, key from env `APP_SECRET_KEY`)
- LLM API Key stored in DB (same encryption)
- No user authentication for v1 (single-user) — expose only via docker network
- CORS restricted to same-origin
- Input sanitization on all RSS feed URLs (no SSRF beyond intended)
- Rate limit article generation to prevent runaway API costs

### 7.4 Logging & Monitoring

- Structured JSON logging (structlog)
- Per-article generation log: prompt tokens, completion tokens, latency, model used
- Schedule run log: feeds fetched, articles generated, errors
- Dashboard shows: last 24h summary, error rate, API cost estimate
- Docker healthcheck: `GET /health` endpoint (returns DB connectivity, schedule status)

---

## 8. Dependencies (requirements.txt)

```
# Web framework
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
jinja2>=3.1.4
python-multipart>=0.0.17  # form parsing

# Database
sqlalchemy[asyncio]>=2.0.36
aiosqlite>=0.20.0

# LLM client
httpx>=0.28.0

# RSS
feedparser>=6.0.11

# Scheduling
apscheduler>=3.10.4

# Encryption (API key storage)
cryptography>=44.0.0

# Settings
pydantic-settings>=2.7.0

# Content processing
markdown>=3.7.0
readability-lxml>=0.8.1
trafilatura>=1.12.0      # fallback content extraction

# Logging
structlog>=25.1.0

# Dev
aiofiles>=24.1.0
```

---

## 9. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Single container** | No need for separate worker/UI containers — APScheduler background thread handles scheduling in-process. Simpler deploy. |
| **Server-rendered (no SPA)** | Single-user admin UI doesn't need React/Vue complexity. Jinja2 + HTMX (optional) gives fast, simple interactivity. |
| **SQLite over Postgres** | Zero-config, no separate container, perfect for single-user. WAL mode handles concurrent reads. |
| **Jinja2 macros for components** | Matching the Revolut design system's component-based tokens naturally maps to Jinja2 include/macro system. |
| **Structured LLM output** | Using JSON mode or function calling guarantees parseable article structure. Avoids regexing prose for metadata. |
| **No WebSocket / SSE** | Article generation takes 10-30s — polling is simpler and adequate for a single-user admin UI. |

---

## 10. Future Enhancements (Post-MVP)

- [ ] Multi-user auth (session-based)
- [ ] Article templates (customize structure per prompt)
- [ ] Image generation (DALL-E / Unsplash API for feature images)
- [ ] Internal link discovery (search existing Ghost content for link opportunities)
- [ ] Bulk generation queue (generate N articles, review in batch)
- [ ] Ghost webhook receiver (trigger generation on new tag/event)
- [ ] Article scheduling (set publish date in Ghost via `published_at`)
- [ ] Keyword rank tracking
- [ ] OpenAI-compatible streaming preview in UI
- [ ] Export/import config (portable setup)

---

## 11. File Creation Order

| Order | File | Phase |
|-------|------|-------|
| 1 | `requirements.txt` | P1 |
| 2 | `.env.example` | P1 |
| 3 | `Dockerfile` | P1 |
| 4 | `docker-compose.yml` | P1 |
| 5 | `app/__init__.py` | P1 |
| 6 | `app/config.py` | P1 |
| 7 | `app/database.py` | P1 |
| 8 | `app/models/base.py` | P1 |
| 9 | `app/models/*.py` (all models) | P1 |
| 10 | `app/main.py` | P1 |
| 11 | `app/services/llm_client.py` | P2 |
| 12 | `app/services/ghost_client.py` | P2 |
| 13 | `app/services/rss_fetcher.py` | P2 |
| 14 | `app/services/article_generator.py` | P2 |
| 15 | `app/services/scheduler.py` | P4 |
| 16 | `app/static/css/tokens.css` | P3 |
| 17 | `app/static/css/main.css` | P3 |
| 18 | `app/static/js/app.js` | P3 |
| 19 | `app/templates/components/*.html` | P3 |
| 20 | `app/templates/base.html` | P3 |
| 21 | `app/templates/dashboard.html` | P3 |
| 22 | `app/templates/prompts/*.html` | P3 |
| 23 | `app/templates/feeds/*.html` | P3 |
| 24 | `app/templates/schedules/*.html` | P3 |
| 25 | `app/templates/settings.html` | P3 |
| 26 | `app/templates/articles/*.html` | P3 |
| 27 | `app/routers/*.py` (all routers) | P3 |
| 28 | `app/utils/seo.py` | P5 |
| 29 | `.dockerignore` | P1 |

---

## 12. Verification Gates

After each phase completes:
- **P1**: `docker build` succeeds, FastAPI serves `GET /health` → 200
- **P2**: Unit tests for each service (mock LLM, mock Ghost API, mock RSS)
- **P3**: All UI routes render without error, mobile responsive at breakpoints
- **P4**: Schedules fire on cron, articles appear in DB with correct data
- **P5**: End-to-end: RSS feed → LLM generation → Ghost publish → article visible on blog

---

*Generated: 2026-06-09 | This is the architecture blueprint. Ready for Momus review before implementation kickoff.*
