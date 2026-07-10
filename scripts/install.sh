#!/usr/bin/env bash
set -euo pipefail

REPO="opennavicat/opennavicat"
INSTALL_DIR="${INSTALL_DIR:-/usr/local/bin}"

# Detect OS
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
  Linux)  OS=linux ;;
  Darwin) OS=macos ;;
  *)      echo "Unsupported OS: $OS"; exit 1 ;;
esac

case "$ARCH" in
  x86_64|amd64) ARCH=x86_64 ;;
  aarch64|arm64) ARCH=arm64 ;;
  *)            echo "Unsupported arch: $ARCH"; exit 1 ;;
esac

# Fetch latest release
echo "Fetching latest release..."
URL=$(curl -s "https://api.github.com/repos/$REPO/releases/latest" \
  | grep "browser_download_url.*${OS}.*${ARCH}.*tar.gz" \
  | head -1 | cut -d '"' -f 4)

if [ -z "$URL" ]; then
  echo "No prebuilt binary found — falling back to pip install"
  pip install opennavicat
  exit 0
fi

echo "Downloading $URL"
curl -sL "$URL" -o /tmp/opennavicat.tar.gz
tar xzf /tmp/opennavicat.tar.gz -C "$INSTALL_DIR" opennavicat
chmod +x "$INSTALL_DIR/opennavicat"
rm /tmp/opennavicat.tar.gz
echo "Installed opennavicat to $INSTALL_DIR/opennavicat"
