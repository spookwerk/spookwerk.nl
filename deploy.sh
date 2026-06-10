#!/usr/bin/env bash
# spookwerk.nl deploy guard — the ONLY sanctioned deploy path (spec E §8).
# Verifies the site, then scp's an explicit allowlist to TransIP.
# NEVER add deletion-capable sync (rsync --delete etc.): the server docroot
# holds index.php.bak and the webhook secrets live above docroot — both must
# survive every deploy untouched.
set -euo pipefail
cd "$(dirname "$0")"

HOST=spookw.ssh.transip.me

if [ -n "$(git status --porcelain)" ]; then
    echo "WARNING: git tree is dirty — the GitHub mirror should match what goes live." >&2
fi

echo "== verify =="
python3 tools/verify-seo.py

echo "== ensure target dirs =="
ssh "$HOST" 'mkdir -p www/og www/hooks www/en www/apps/huurscan www/apps/vitadatum'

echo "== upload (explicit allowlist) =="
FILES=(
  index.html
  en/index.html
  sitemap.xml
  robots.txt
  llms.txt
  og/default.png
  favicon.svg
  favicon.ico
  favicon-16x16.png
  favicon-32x32.png
  apple-touch-icon.png
  icon-192.png
  icon-512.png
  site.webmanifest
  wordmark.svg
  apps/huurscan/icon.png
  apps/vitadatum/icon.png
  hooks/asc.php
)
for f in "${FILES[@]}"; do
  scp -q "$f" "$HOST:www/$f"
  echo "  $f"
done

echo "== smoke check =="
fail=0
for path in / /en/ /sitemap.xml /robots.txt /llms.txt; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "https://spookwerk.nl$path")
  echo "  $code https://spookwerk.nl$path"
  [ "$code" = "200" ] || fail=1
done
if [ "$fail" != 0 ]; then
  echo "SMOKE CHECK FAILED — files are already uploaded; investigate immediately." >&2
  exit 1
fi
echo "Deploy OK."
