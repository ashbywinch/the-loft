#!/bin/sh
# The model gateway for anything that hits the model — the evals, the trials,
# the one-off measurements.
#
# Every such run needs OPENAI_BASE_URL + OPENAI_API_KEY, the Cloudflare AI
# Gateway (`skill://cloudflare-ai-gateway`): the compat endpoint and the
# gateway token. Two things go wrong without this wrapper, both observed:
#
#   1. A shell — or an agent session — with OPENAI_BASE_URL pointed at a local
#      proxy silently sends the evals somewhere else. The failure is a 400 deep
#      inside a paid call, and the numbers that come back describe an engine
#      nobody chose. So .env's value is loaded LAST (it is the project's own)
#      and a base URL that is not the gateway is refused here, loudly.
#   2. PYTHONPATH was being set by hand for `python -m tools.…`. Here it is set
#      once, for every child.
#
# Usage: scripts/model-env.sh <command> [args…]
set -eu

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091  # .env is the operator's file, not a source artifact
  . ./.env
  set +a
fi

# The gateway token lives in the shell (never in a file). It is set
# UNCONDITIONALLY: an inherited OPENAI_API_KEY is a different endpoint's key —
# this session's own proxy key produced a 401 from the gateway while looking
# perfectly configured. The skill's name for the token is
# CLOUDFLARE_AIGATEWAY_TOKEN; the clients' name is OPENAI_API_KEY.
OPENAI_API_KEY="${CLOUDFLARE_AIGATEWAY_TOKEN:-}"

case "${OPENAI_BASE_URL:-}" in
  https://gateway.ai.cloudflare.com/*) ;;
  *)
    echo "model-env: OPENAI_BASE_URL is not the Cloudflare gateway." >&2
    echo "  got: ${OPENAI_BASE_URL:-<unset>}" >&2
    echo "  set it in .env (the project's own, loaded here last):" >&2
    echo "    OPENAI_BASE_URL=https://gateway.ai.cloudflare.com/v1/<account>/<gateway>/compat" >&2
    exit 1
    ;;
esac

if [ -z "$OPENAI_API_KEY" ]; then
  echo "model-env: no gateway token. Export CLOUDFLARE_AIGATEWAY_TOKEN (or set" >&2
  echo "  OPENAI_API_KEY) in the shell — tokens never live in the repo." >&2
  exit 1
fi

export OPENAI_API_KEY
export PYTHONPATH="$(pwd)"
exec "$@"
