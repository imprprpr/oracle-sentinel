#!/usr/bin/env bash
# ==============================================================================
# Oracle Sentinel - Update GeoIP and GeoSite Databases
# Source: MetaCubeX / LoyalSoldier / v2fly
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GEO_DIR="$SCRIPT_DIR/static/geo"

mkdir -p "$GEO_DIR"

echo ">>> Updating GeoIP databases to $GEO_DIR ..."

echo "1. Downloading GeoSite.dat..."
curl -fsSL "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geosite.dat" -o "$GEO_DIR/geosite.dat"

echo "2. Downloading GeoIP.dat..."
curl -fsSL "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geoip.dat" -o "$GEO_DIR/geoip.dat"

echo "3. Downloading country.mmdb..."
curl -fsSL "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/country.mmdb" -o "$GEO_DIR/country.mmdb"

echo "[OK] Geo databases updated successfully!"
ls -lh "$GEO_DIR"
