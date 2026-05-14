"""Anthropic Messages API client for CircuitPython on the T-Deck.

Synchronous; blocks the caller until the response comes back. Returns the
raw response dict so callers can drive the tool-use loop themselves.

Uses adafruit_connection_manager for the socket pool and SSL context so
those expensive resources are pooled across requests instead of leaked.
On a transport failure we forcibly close all open sockets via the
connection manager — this is the only reliable way to recover from a
half-dead TLS connection that the kernel still thinks is alive.
"""
import gc
import time
import wifi
import adafruit_requests
import adafruit_connection_manager

API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

# Fallback for when the server hits 429 but didn't send a Retry-After
# header (or sent something we can't parse). 60s is the natural per-
# minute rate-limit window for the Messages API.
DEFAULT_RETRY_AFTER_S = 60

# Hard ceiling for a single API call. Without this, a stalled socket
# blocks the entire bot scene indefinitely — there's no thread doing
# the I/O off the scene update loop. 120s is plenty of headroom for
# even a long Sonnet response with multi-tool turns; anything beyond
# that is almost certainly a hung connection that the retry loop
# should pick up and rebuild from scratch.
REQUEST_TIMEOUT_S = 120

_session = None


class RateLimitError(Exception):
    """Raised on HTTP 429. `retry_after_s` is what the caller should
    sleep before retrying the same request."""

    def __init__(self, retry_after_s, message=""):
        super().__init__(message or "rate limited")
        self.retry_after_s = retry_after_s


# Number of attempts (1 initial + N-1 retries) on socket-level failures.
# 5 attempts with the backoff schedule (1, 2, 4, 8, 16s) covers ~30s of
# transient flakes — enough for most wifi blips while still failing
# fast on a real outage.
TRANSPORT_ATTEMPTS = 5
TRANSPORT_BACKOFF_CAP_S = 16
TRANSPORT_KEYWORDS = (
    "socket", "connection", "timeout", "broken pipe",
    "reset", "eagain", "epipe", "econnreset", "failed",
)


def _is_transient(e):
    """Heuristic: did this exception look like a transport-level glitch
    that's worth retrying with a fresh session?"""
    if isinstance(e, OSError):
        return True
    msg = str(e).lower()
    return any(k in msg for k in TRANSPORT_KEYWORDS)


def _session_singleton():
    global _session
    if _session is None:
        # connection_manager caches the pool + SSL context per-radio
        # internally, so repeated reset cycles don't leak new ones.
        # The previous approach of creating fresh SocketPool/SSLContext
        # objects on every reset eventually exhausted the small
        # ESP32-S3 socket table after many reconnects.
        pool = adafruit_connection_manager.get_radio_socketpool(wifi.radio)
        ssl_ctx = adafruit_connection_manager.get_radio_ssl_context(wifi.radio)
        _session = adafruit_requests.Session(pool, ssl_ctx)
    return _session


def reset_session():
    """Drop the cached Session AND forcibly close every open socket the
    connection manager is tracking.

    The forced close is the critical bit: a half-dead TLS connection
    that the OS still considers "alive" will keep failing reads/writes
    until the underlying socket is yanked out from under it. Without
    this, a long agent session accumulates dead sockets and every
    subsequent request fails with 'repeated socket failures'.
    """
    global _session
    try:
        adafruit_connection_manager.connection_manager_close_all(
            release_references=False)
    except Exception as e:
        # Best effort — if the close fails we still want to retry.
        print("connection_manager_close_all failed:", e)
    _session = None
    # Free heap pressure from the dropped session before opening a new
    # one. Long sessions on ESP32-S3 fragment without periodic gc.
    gc.collect()


def _wifi_ok():
    """Quick yes/no for whether wifi looks usable. We don't try to
    reconnect (config-time setup owns that), but flagging a dropped
    link helps callers distinguish 'API is down' from 'we lost wifi'."""
    try:
        return wifi.radio.ipv4_address is not None
    except Exception:
        return False


def send_messages(api_key, model, messages, max_tokens=1024, system=None, tools=None,
                  cache=True):
    """POST /v1/messages and return the parsed response dict.

    `messages` follows the Anthropic format. `tools` is an optional list of
    tool specs (see client/llm/tools.py).

    When `cache=True` (default), the system prompt and tools array are
    marked with `cache_control: ephemeral`, which puts the static prefix
    into Anthropic's prompt-cache for ~5 minutes. On a multi-turn tool-
    use loop this is the difference between paying full input-tokens
    on every request vs. only the delta — i.e. the difference between
    hitting per-minute rate limits and not.

    Raises RuntimeError on non-200; raises RateLimitError on HTTP 429
    (which carries retry_after_s for retry logic); raises whatever
    adafruit_requests raises on transport errors.
    """
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        if cache:
            # Wrap the system prompt in a single content block flagged
            # as the cache breakpoint. Anthropic caches everything up
            # to and including this block.
            body["system"] = [{
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }]
        else:
            body["system"] = system
    if tools:
        if cache and len(tools) > 0:
            # Tag the *last* tool definition as a cache breakpoint so
            # the entire tools array (the heaviest static payload) is
            # cached together with the system prompt. Deep-copy the
            # last entry to avoid mutating the caller's TOOL_SPECS list.
            cached_tools = list(tools)
            last = dict(cached_tools[-1])
            last["cache_control"] = {"type": "ephemeral"}
            cached_tools[-1] = last
            body["tools"] = cached_tools
        else:
            body["tools"] = tools
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    # Retry transient socket errors (stale TLS, wifi blip, server-side
    # keep-alive timeout) with a fresh session. Rate-limit (429) and
    # other HTTP-level errors aren't retried here — they belong to the
    # caller's higher-level loop.
    last_err = None
    for attempt in range(TRANSPORT_ATTEMPTS):
        try:
            s = _session_singleton()
            # `timeout` is a per-request socket timeout supported by
            # adafruit_requests >=1.x. If the server stops sending
            # data for that many seconds the underlying socket raises
            # OSError, which our transient-error retry catches.
            r = s.post(API_URL, headers=headers, json=body,
                       timeout=REQUEST_TIMEOUT_S)
            try:
                if r.status_code == 429:
                    # Honor whatever Retry-After the server tells us,
                    # falling back to 60s if absent/unparseable.
                    wait_s = DEFAULT_RETRY_AFTER_S
                    try:
                        ra = r.headers.get("retry-after") if r.headers else None
                        if ra:
                            wait_s = int(ra)
                    except (ValueError, TypeError):
                        pass
                    detail = ""
                    try:
                        detail = r.text[:200] if r.text else ""
                    except Exception:
                        pass
                    raise RateLimitError(wait_s, detail)
                if r.status_code != 200:
                    raise RuntimeError(
                        "HTTP {}: {}".format(r.status_code, r.text[:200]))
                return r.json()
            finally:
                r.close()
        except RateLimitError:
            # Higher layer (bot_scene) handles rate-limit retries.
            raise
        except Exception as e:
            if not _is_transient(e):
                raise
            last_err = e
            print("transport error (attempt {}/{}):".format(
                attempt + 1, TRANSPORT_ATTEMPTS), e)
            # Forcibly close all open sockets the connection manager
            # is tracking, drop the cached session, and free memory
            # before the next attempt. Plain reset (just nulling the
            # session) doesn't unstick a half-dead socket — the kernel
            # still considers it alive and adafruit_requests will keep
            # trying to use it.
            reset_session()
            if attempt < TRANSPORT_ATTEMPTS - 1:
                backoff = 1 << attempt           # 1, 2, 4, 8, 16
                if backoff > TRANSPORT_BACKOFF_CAP_S:
                    backoff = TRANSPORT_BACKOFF_CAP_S
                time.sleep(backoff)
    # All attempts exhausted — surface a useful summary. If wifi has
    # dropped, that's the real problem and we say so.
    wifi_note = "" if _wifi_ok() else " (wifi appears disconnected)"
    raise RuntimeError(
        "repeated transport failures after {} attempts{}: {}".format(
            TRANSPORT_ATTEMPTS, wifi_note, last_err))
