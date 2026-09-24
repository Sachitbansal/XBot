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
THRESHOLD = 7.5
SCORE_WEIGHTS = {
    "virality": 0.30,
    "novelty": 0.25,
    "technical": 0.20,
    "relevance": 0.15,
    "discussion": 0.10,
}
# What "relevance" is judged against.
AUDIENCE = (
    "developers, AI/ML engineers and indie builders on X who care about AI, LLMs, agents, "
    "open source, dev tools, infra and startups"
)
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

STYLE_INSTRUCTION = (
    "concise, technical but understandable, builder perspective, slightly provocative, "
    "no corporate language, occasional dry humor, don't overuse emojis, don't sound like an AI"
)

# --- Sources ---------------------------------------------------------------
HTTP_TIMEOUT_SECONDS = 20
USER_AGENT = "xbot-content-radar/0.1 (personal use)"

HN_STORY_LISTS = ["topstories", "newstories"]
HN_MAX_PER_LIST = 30
HN_MIN_POINTS = 50  # skip low-signal stories
# HN is mostly tech already; the scorer's relevance axis does the real filtering.
# Flip on if volume/LLM cost gets too high.
HN_KEYWORD_FILTER = False
HN_TECH_KEYWORDS = [
    "ai", "llm", "gpt", "model", "agent", "open source", "rust", "python", "gpu",
    "nvidia", "openai", "anthropic", "claude", "gemini", "llama", "inference",
    "database", "postgres", "linux", "kernel", "compiler", "startup", "api",
    "security", "robot", "ml", "neural", "transformer", "benchmark", "chip",
]

ARXIV_CATEGORIES = ["cs.AI", "cs.LG", "cs.CL"]
ARXIV_MAX_RESULTS = 40
ARXIV_LOOKBACK_HOURS = 48  # arXiv listing lags submission; dedupe handles overlap

GITHUB_TRENDING_URL = "https://github.com/trending?since=daily"
GITHUB_TRENDING_MAX = 25

RSS_FEEDS = {
    "techcrunch": "https://techcrunch.com/feed/",
    "arstechnica": "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "theverge": "https://www.theverge.com/rss/index.xml",
    "simonwillison": "https://simonwillison.net/atom/everything/",
    "hf_blog": "https://huggingface.co/blog/feed.xml",
}
RSS_MAX_PER_FEED = 15
RSS_LOOKBACK_HOURS = 24

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
ENABLED_SOURCES = ["hackernews", "arxiv", "github_trending", "rss", "x_search"]
