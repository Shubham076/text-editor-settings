#!/usr/bin/env bash
# Build px0 from source with our themes and patches, and install it.
#
#   ./install.sh            update src/ to upstream master, then build and install
#   ./install.sh --no-pull  rebuild the commit src/ is already on
#
# src/ is a clone of github.com/px0-ai/px0 that this script owns: every run resets
# it, so local changes belong in patches/*.patch and themes/*.css, never in src/.
#   patches/*.patch   applied in name order (user keybindings support)
#   themes/*.css      copied into web/themes/, which px0 embeds as built-in themes
#   keybindings.json  symlinked to ~/.px0/keybindings.json, read at runtime
#
# Env: PX0_BIN (default ~/.local/bin), PX0_REF (default origin/master).
# `px0 --update` would swap this build for an upstream release; rerun this instead.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$DIR/src"
BIN="${PX0_BIN:-$HOME/.local/bin}"
REF="${PX0_REF:-origin/master}"
PULL=1
[[ "${1:-}" == "--no-pull" ]] && PULL=0

for tool in git go node; do
  command -v "$tool" >/dev/null || { echo "install.sh: $tool is required" >&2; exit 1; }
done

if [[ ! -d "$SRC/.git" ]]; then
  git clone https://github.com/px0-ai/px0.git "$SRC"
fi

cd "$SRC"
if (( PULL )); then
  git fetch --quiet origin
  git reset --quiet --hard "$REF"
else
  git reset --quiet --hard HEAD
fi
git clean --quiet -fd

for p in "$DIR"/patches/*.patch; do
  [[ -e "$p" ]] || continue
  echo "patch   $(basename "$p")"
  git apply "$p"
done

for t in "$DIR"/themes/*.css; do
  [[ -e "$t" ]] || continue
  echo "theme   $(basename "$t" .css)"
  cp "$t" web/themes/
done

node ./scripts/build-web.js
mkdir -p "$BIN"
CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o "$BIN/px0" .

# Same place px0 looks for settings.json (settingsPath in settings.go).
CONF="${XDG_CONFIG_HOME:+$XDG_CONFIG_HOME/px0}"
CONF="${CONF:-$HOME/.px0}"
mkdir -p "$CONF"
ln -sfn "$DIR/keybindings.json" "$CONF/keybindings.json"

echo "installed $("$BIN/px0" --version) at $BIN/px0 ($(git rev-parse --short HEAD))"
