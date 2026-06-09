# Draft: GhostWriter Automated Blog System

## Requirements (confirmed)
- [ghost-integration]: Connect to Ghost blog via Admin API for creating/publishing posts
- [llm-flexibility]: Support both local LLM (Ollama) AND OpenAI-compatible remote APIs (Claude, GPT, Deepseek, Gemini)
- [docker-deployment]: Docker container via docker-compose, web UI at port 3639
- [web-ui]: Configuration UI for prompts, content sources (RSS feeds), LLM selection, generation schedule
- [design-reference]: Web UI follows Revolut-inspired design system from DESIGN.MD
- [auto-content]: Automatically find latest news on assigned topics and create SEO-optimized articles
- [scheduling]: Configurable article generation frequency

## Technical Decisions
- (pending research)

## Research Findings
- (pending - 4 background agents running)

## Open Questions
- Technology stack preference? Python (FastAPI) vs Node.js vs Go?
- Local LLM — use Ollama as sidecar container?
- Database for storing config, prompts, articles, schedule — SQLite (simple) vs Postgres?
- Are there existing RSS feeds / topics you already have in mind?
- Do you want Ghost installed in the same compose file, or is it already running separately?
- Multi-user or single-user UI?
- Any specific SEO requirements beyond meta tags, OG images, keyword insertion?

## Scope Boundaries
- INCLUDE: Docker container, web UI, Ghost Admin API integration, LLM integration (local + remote), RSS ingestion, article generation pipeline, scheduling, SEO optimization
- EXCLUDE: (pending)
