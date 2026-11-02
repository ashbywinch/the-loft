"""The model configuration — the one file that names the models and the gateway.

Every model call in the pipeline resolves its endpoint and model name here, so
a model change is one edit, and no call site carries a stale alias. The endpoint
is the Cloudflare AI Gateway's OpenAI-compatible interface: `OPENAI_BASE_URL`
(the gateway's `/compat` URL, set in `.env`) and `OPENAI_API_KEY` (the gateway
token, set in the shell — see `scripts/model-env.sh` and
`skill://cloudflare-ai-gateway`).

The aliases are the gateway's own routing names, not provider-specific ids:
`dynamic/image` is the vision model the gateway resolves, `dynamic/fallback2`
the chat default, and `deepseek/deepseek-v4-flash` the provider-qualified id the
boundary call asks for (the gateway requires `<provider>/<model>`).
"""

from __future__ import annotations

import os

# the endpoint: the Cloudflare AI Gateway's OpenAI-compatible URL, from the
# environment the operator sources (`.env` + scripts/model-env.sh)
GATEWAY_VAR = "OPENAI_BASE_URL"
CLOUDFLARE_GATEWAY_PREFIX = "https://gateway.ai.cloudflare.com/"
GATEWAY_BASE_URL: str = os.environ.get(GATEWAY_VAR, "")

# the model aliases — the ONE place they are written
VISION_MODEL = "dynamic/image"  # classify, orient, printed and structured reads
CHAT_MODEL = "dynamic/fallback2"  # the general chat default
BOUNDARY_MODEL = "deepseek/deepseek-v4-flash"  # the document-boundary judgment


def gateway_base_url() -> str:
    """The endpoint every call uses; a missing value is a configuration error,
    stated as one rather than silently falling back to another provider."""
    if not GATEWAY_BASE_URL:
        raise RuntimeError(
            "no model endpoint: set OPENAI_BASE_URL to the Cloudflare AI Gateway's /compat URL "
            "(scripts/model-env.sh loads .env for you)"
        )
    return GATEWAY_BASE_URL
