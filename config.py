"""All tunables live here. Secrets come from .env, never hardcoded."""
import os

from dotenv import load_dotenv

load_dotenv()

# --- Secrets / connections -------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://xbot:xbot@localhost:5440/xbot")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTERKEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")
SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")
GOOGLE_CSE_KEY = os.environ.get("GOOGLE_CSE_KEY", "")
GOOGLE_CSE_CX = os.environ.get("GOOGLE_CSE_CX", "")

# --- LLM -------------------------------------------------------------------
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Testing phase: free models. Free tier gets upstream 429s often, so each role
# has a fallback list (OpenRouter tries them in order).
# Final: swap both to ["qwen/qwen-2.5-72b-instruct"].
SCORING_MODELS = [
    "qwen/qwen3.8-27b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
]
GENERATION_MODELS = list(SCORING_MODELS)

# Token caps include hidden reasoning tokens on thinking models — keep generous.
SCORING_TEMPERATURE = 0.2
SCORING_MAX_TOKENS = 2000
GENERATION_TEMPERATURE = 0.9
GENERATION_MAX_TOKENS = 4000
LLM_REASONING_EFFORT = "low"  # ignored by non-reasoning models

LLM_TIMEOUT_SECONDS = 90
LLM_MAX_RETRIES = 4
LLM_RETRY_BASE_DELAY = 5  # seconds, exponential backoff

# --- Scoring ---------------------------------------------------------------
THRESHOLD = 6.0  # spec default 7.5; lowered during build phase to see more drafts
# Spec default was 0.30/0.25/0.20/0.15/0.10. Shifted toward reach: posts are for
# attention/follows, so technical depth barely counts. Must sum to 1.0.
SCORE_WEIGHTS = {
    "virality": 0.35,
    "novelty": 0.25,
    "technical": 0.05,
    "relevance": 0.15,
    "discussion": 0.20,
}
# Sachit's niche. Scoring relevance and draft framing are both anchored to this.
NICHE = (
    "AI and GenAI, AI agents, automation, cybersecurity, web dev, general software dev, "
    "open source (incl. GSoC and contributor culture), SaaS startup ideas and new SaaS/dev-tool "
    "startups, trending GitHub repos"
)
AUDIENCE = f"developers, indie hackers and builders on X who follow: {NICHE}"
# Niche gate: items below this relevance score never get drafts, however viral.
MIN_RELEVANCE_TO_DRAFT = 6
# Cap LLM scoring calls per cycle so a first run / big backlog can't blow the budget.
MAX_ITEMS_TO_SCORE_PER_CYCLE = 60
# Trim raw_content before sending to the scorer.
SCORE_CONTENT_CHARS = 1500

# --- Generation ------------------------------------------------------------
# Toggle angles off here if one underperforms.
ANGLES = {
    "technical_insight": True,
    "contrarian": True,
    "builder_pov": True,
    "short_punchy": True,
    "quote_post": True,
}
SHORT_PUNCHY_MAX_CHARS = 200
X_MAX_CHARS = 280
# Safety valve against spam: max items drafted in a single cycle (highest composite first).
MAX_ITEMS_TO_DRAFT_PER_CYCLE = 3

# Where drafts go for review. "markdown" (build phase) writes to DRAFTS_DIR and you
# review with `python review.py`; "telegram" sends to the bot.
OUTPUT_MODE = "markdown"  # "markdown" | "telegram"
DRAFTS_DIR = "output/drafts"

# Anti-spam for sending: never send drafts older than this, and cap sends per cycle.
SEND_MAX_DRAFT_AGE_HOURS = 12
MAX_DRAFTS_SENT_PER_CYCLE = 15

STYLE_INSTRUCTION = (
    "concise, plain language anyone in tech can follow, builder perspective, slightly provocative, "
    "no jargon dumps, no corporate language, occasional dry humor, don't overuse emojis, "
    "don't sound like an AI"
)
# The point of every post: reach. Nerdy/academic summaries don't get followers.
POST_GOAL = (
    "grab attention in the first line, get views, replies and follows. Lead with why it "
    "matters or what's surprising, not with how it works"
)
# Drafts containing any of these are dropped (case-insensitive). Free models copy
# stock openers verbatim, which makes every post read like a template.
BANNED_PHRASES = [
    "everyone's talking about",
    "the more important story",
    "the interesting part about",
    "if i were building",
    "here's why",
    "game changer",
    "game-changer",
    "let's dive in",
    "buckle up",
    "in today's world",
    "the real story",
    "isn't just",
    "it's not just",
    # generic engagement bait; questions must be specific to the item
    "thoughts?",
    "what do you think?",
    "agree?",
    "let me know in the comments",
]
# Sources where the author has NOT consumed the full thing (only title + abstract/summary).
SUMMARY_ONLY_SOURCES = ("arxiv", "hf_papers")

# --- Sources ---------------------------------------------------------------
HTTP_TIMEOUT_SECONDS = 20
USER_AGENT = "xbot-content-radar/0.1 (personal use)"

HN_STORY_LISTS = ["topstories", "newstories"]
HN_MAX_PER_LIST = 30
HN_MIN_POINTS = 50  # skip low-signal stories
# HN is mostly tech already; the scorer's relevance axis does the real filtering.
# Flip on if volume/LLM cost gets too high.
HN_KEYWORD_FILTER = False
HN_TECH_KEYWORDS = [  # only used if HN_KEYWORD_FILTER
    "ai", "llm", "gpt", "model", "agent", "open source", "rust", "python", "gpu",
    "nvidia", "openai", "anthropic", "claude", "gemini", "llama", "inference",
    "database", "postgres", "linux", "kernel", "compiler", "startup", "api",
    "security", "robot", "ml", "neural", "transformer", "benchmark", "chip",
]

ARXIV_CATEGORIES = ["cs.AI", "cs.LG", "cs.CL"]
ARXIV_MAX_RESULTS = 40
ARXIV_LOOKBACK_HOURS = 48  # arXiv listing lags submission; dedupe handles overlap

# Overall + niche languages; the same repo across pages is deduped.
GITHUB_TRENDING_URLS = [
    "https://github.com/trending?since=daily",
    "https://github.com/trending/python?since=daily",
    "https://github.com/trending/typescript?since=daily",
]
GITHUB_TRENDING_MAX = 25  # per page
GITHUB_README_CHARS = 2500  # README excerpt fed to generation for repo items

RSS_FEEDS = {
    # AI / GenAI
    "simonwillison": "https://simonwillison.net/atom/everything/",
    "hf_blog": "https://huggingface.co/blog/feed.xml",
    "latent_space": "https://www.latent.space/feed",
    "tldr_ai": "https://tldr.tech/api/rss/ai",
    # general tech / startups / launches
    "techcrunch": "https://techcrunch.com/feed/",
    "techmeme": "https://www.techmeme.com/feed.xml",
    "arstechnica": "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "tldr_founders": "https://tldr.tech/api/rss/founders",
    "producthunt": "https://www.producthunt.com/feed",
    "show_hn": "https://hnrss.org/show?points=50",
    # open source
    "github_blog": "https://github.blog/feed/",
    # web dev
    "tldr_webdev": "https://tldr.tech/api/rss/webdev",
    "javascript_weekly": "https://javascriptweekly.com/rss",
    # cybersecurity
    "thehackernews": "https://feeds.feedburner.com/TheHackersNews",
    "bleepingcomputer": "https://www.bleepingcomputer.com/feed/",
    "krebs": "https://krebsonsecurity.com/feed/",
    "tldr_infosec": "https://tldr.tech/api/rss/infosec",
    # communities (Reddit: ~20s rate-limit wait per feed, see below)
    "reddit_localllama": "https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day",
    "reddit_machinelearning": "https://www.reddit.com/r/MachineLearning/top/.rss?t=day",
    "reddit_ai_agents": "https://www.reddit.com/r/AI_Agents/top/.rss?t=day",
    "reddit_saas": "https://www.reddit.com/r/SaaS/top/.rss?t=day",
    "reddit_webdev": "https://www.reddit.com/r/webdev/top/.rss?t=day",
    "reddit_netsec": "https://www.reddit.com/r/netsec/top/.rss?t=day",
}
RSS_MAX_PER_FEED = 15
RSS_LOOKBACK_HOURS = 24
# Reddit allows ~1 unauthenticated request per window; on 429 wait for its
# x-ratelimit-reset (fallback RSS_RETRY_DELAY_SECONDS, capped) and retry once.
RSS_RETRY_DELAY_SECONDS = 5
RSS_MAX_RETRY_WAIT_SECONDS = 60

HF_PAPERS_MAX = 20            # top daily papers by upvotes
HF_MODELS_MAX = 20            # top trending models
HF_MODELS_MAX_AGE_DAYS = 14   # skip long-trending old models

LOBSTERS_MIN_SCORE = 15
DEVTO_MAX = 20
DEVTO_MIN_REACTIONS = 30

# X-trending-via-search. "none" disables the source.
SEARCH_PROVIDER = "none"  # "brave" | "serpapi" | "google_cse" | "none"
X_SEARCH_QUERIES = [
    "AI agents site:x.com",
    "open source AI model release site:x.com",
    "LLM benchmark site:x.com",
    "new developer tool launch site:x.com",
]
X_SEARCH_RESULTS_PER_QUERY = 10

# Which sources run each cycle.
ENABLED_SOURCES = ["hackernews", "arxiv", "hf_papers", "hf_models", "github_trending",
                   "lobsters", "devto", "rss", "x_search"]
