"""Single entry point for every LLM call (OpenRouter). Swap models/providers here only."""
import json
import logging
import re
import time

import httpx

import config

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    pass


def chat(messages: list[dict], models: list[str], *, json_mode: bool = False,
         temperature: float = 0.7, max_tokens: int = 1200) -> tuple[str, str]:
    """Run one chat completion. Returns (content, model_actually_used).

    `models` is a fallback list: OpenRouter tries them in order on provider errors.
    On top of that we retry the whole call with exponential backoff.
    """
    if not config.OPENROUTER_API_KEY:
        raise LLMError("OPENROUTER_API_KEY not set")

    payload = {
        "model": models[0],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        # Thinking models: keep reasoning short and out of `content`.
        "reasoning": {"effort": config.LLM_REASONING_EFFORT, "exclude": True},
    }
    if len(models) > 1:
        payload["models"] = models
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "X-Title": "xbot-content-radar",
    }

    last_err = None
    for attempt in range(config.LLM_MAX_RETRIES):
        try:
            resp = httpx.post(config.OPENROUTER_URL, json=payload, headers=headers,
                              timeout=config.LLM_TIMEOUT_SECONDS)
            try:
                data = resp.json() if resp.content else {}
            except ValueError:  # HTML error page from a gateway
                data = {"error": {"code": resp.status_code, "message": resp.text[:200]}}
            err = data.get("error")
            if resp.status_code in RETRYABLE_STATUS or (err and err.get("code") in RETRYABLE_STATUS):
                last_err = f"{resp.status_code}: {err or resp.text[:200]}"
            elif resp.status_code != 200 or err:
                raise LLMError(f"OpenRouter {resp.status_code}: {err or resp.text[:300]}")
            else:
                content = (data["choices"][0]["message"].get("content") or "").strip()
                if content:
                    return content, data.get("model", models[0])
                last_err = "empty content"
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_err = repr(e)

        delay = config.LLM_RETRY_BASE_DELAY * (2 ** attempt)
        log.warning("LLM call failed (attempt %d/%d): %s — retrying in %ss",
                    attempt + 1, config.LLM_MAX_RETRIES, last_err, delay)
        time.sleep(delay)

    raise LLMError(f"LLM call failed after {config.LLM_MAX_RETRIES} attempts: {last_err}")


def parse_json(text: str) -> dict:
    """Lenient JSON extraction: handles ```json fences and leading/trailing chatter."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise
        return json.loads(m.group(0))


def score(system: str, user: str) -> tuple[dict, str]:
    """Scoring mode: low temperature, JSON output."""
    content, model = chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        config.SCORING_MODELS, json_mode=True, temperature=config.SCORING_TEMPERATURE,
        max_tokens=config.SCORING_MAX_TOKENS,
    )
    return parse_json(content), model


def generate(system: str, user: str, *, json_mode: bool = False) -> tuple[str, str]:
    """Generation mode: higher temperature."""
    return chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        config.GENERATION_MODELS, json_mode=json_mode, temperature=config.GENERATION_TEMPERATURE,
        max_tokens=config.GENERATION_MAX_TOKENS,
    )
