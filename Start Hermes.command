#!/bin/zsh
# Double-click to start Hermes on this Mac, on your private Tailscale link.
# Keep this window open while you (or your friend) use the app; close it to stop.

cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:$HOME/.local/bin:$PATH"

# The AI that works out who says each line.
if ! pgrep -x ollama >/dev/null; then
  echo "Starting Ollama…"
  ollama serve >/tmp/hermes-ollama.log 2>&1 &
fi

# Open the app in the browser once it's up.
( for i in {1..30}; do curl -s -o /dev/null http://localhost:8000/ && break; sleep 1; done
  open http://localhost:8000 ) &

exec uv run hermes serve --tailscale
