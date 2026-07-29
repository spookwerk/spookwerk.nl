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
  .htaccess
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
  wordmark-light.svg
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
for path in / /en/ /sitemap.xml /robots.txt /llms.txt /wordmark-light.svg; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "https://spookwerk.nl$path")
  echo "  $code https://spookwerk.nl$path"
  [ "$code" = "200" ] || fail=1
done
# www must 301 to the apex, not serve the site as a duplicate host (.htaccess).
# A broken .htaccess shows up here as a 500 on the apex checks above; this
# catches the rule being silently ignored (200 = still a duplicate host).
wwwcode=$(curl -s -o /dev/null -w '%{http_code}' "https://www.spookwerk.nl/")
echo "  $wwwcode https://www.spookwerk.nl/ (expect 301)"
[ "$wwwcode" = "301" ] || fail=1

if [ "$fail" != 0 ]; then
  echo "SMOKE CHECK FAILED — files are already uploaded; investigate immediately." >&2
  echo "ROLLBACK: ssh $HOST 'rm www/.htaccess'" >&2
  exit 1
fi
echo "Deploy OK."
