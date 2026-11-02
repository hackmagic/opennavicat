#!/usr/bin/env bash
#
# Offline dependency audit against a local OSV database.
#
# This is the air-gapped counterpart to the `pip-audit` step in ci.yml and
# security-audit.yml: it never contacts osv.dev, so it works with no network
# access and always yields the same answer for the same lockfile.
#
# Usage:
#   scripts/audit_offline.sh              # scan, downloading the DB if uncached
#   scripts/audit_offline.sh --refresh    # force a fresh DB download first
#   scripts/audit_offline.sh --no-download  # never touch the network (air-gapped)
#
# Requires `osv-scanner` on PATH (or set OSV_SCANNER=/path/to/osv-scanner).
# Get it from https://github.com/google/osv-scanner/releases
#
# IMPORTANT: we scan `poetry export`'s requirements.txt, NOT poetry.lock.
# Scanning the lockfile makes osv-scanner report every package in it, including
# optional extras that are switched off (urllib3 only arrives with the
# `clickhouse` extra) and dev-only tools. On this repo that inflated the result
# to 78 findings when the real installed set had none. The export applies the
# lockfile's markers and extras, so it matches what actually ships.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OSV_SCANNER="${OSV_SCANNER:-osv-scanner}"
# Keep the export inside the repo and reference it by a relative name. A
# mktemp path is MSYS-style (/tmp/...) under Git Bash on Windows, and the
# native osv-scanner.exe cannot resolve that, reporting "no package sources".
REQUIREMENTS=".opennavicat-audit-requirements.txt"
trap 'rm -f "$ROOT/$REQUIREMENTS"' EXIT

if ! command -v "$OSV_SCANNER" >/dev/null 2>&1; then
    echo "error: osv-scanner not found (looked for '$OSV_SCANNER')." >&2
    echo "       install it, or set OSV_SCANNER to its path:" >&2
    echo "       https://github.com/google/osv-scanner/releases" >&2
    exit 127
fi

echo "==> exporting the installed dependency set"
# --without-hashes keeps the file readable; the markers and extras are what
# matter here and poetry-plugin-export writes those by default.
poetry export -f requirements.txt --without-hashes -o "$REQUIREMENTS"

# Database cache: ~/.cache/osv-scanner on Linux/macOS, %LOCALAPPDATA%\osv-scalibr
# on Windows. --download-offline-databases still needs the network, so a true
# air-gapped run passes --no-download and uses whatever is already cached.
DB_DIR="${OSV_DB_DIR:-}"
if [[ -z "$DB_DIR" ]]; then
    if [[ -d "${XDG_CACHE_HOME:-$HOME/.cache}/osv-scanner" ]]; then
        DB_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/osv-scanner"
    elif [[ -n "${LOCALAPPDATA:-}" && -d "$LOCALAPPDATA/osv-scalibr" ]]; then
        DB_DIR="$LOCALAPPDATA/osv-scalibr"
    fi
fi

SCAN_ARGS=(scan --offline --verbosity warn)
case "${1:-}" in
    --refresh)
        echo "==> refreshing the OSV database before scanning"
        SCAN_ARGS+=(--download-offline-databases)
        ;;
    --no-download)
        echo "==> using the cached OSV database (no download)"
        ;;
    "")
        # Populate the cache when it is missing, otherwise reuse it.
        if [[ -z "$DB_DIR" ]]; then
            echo "==> no OSV database cached yet, downloading it"
            SCAN_ARGS+=(--download-offline-databases)
        else
            echo "==> using the cached OSV database at $DB_DIR"
        fi
        ;;
    *)
        echo "error: unknown option '$1' (expected --refresh or --no-download)" >&2
        exit 2
        ;;
esac

echo "==> scanning against the local OSV database"
if "$OSV_SCANNER" "${SCAN_ARGS[@]}" "$REQUIREMENTS"; then
    echo "==> no vulnerable dependencies found"
else
    status=$?
    # osv-scanner exits 1 when it *found* vulnerabilities, which is a real
    # result rather than a tool failure; let CI fail but say so plainly.
    echo "==> osv-scanner reported findings (exit $status)" >&2
    exit "$status"
fi
