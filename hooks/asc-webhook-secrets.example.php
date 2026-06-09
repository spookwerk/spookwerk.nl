<?php
/**
 * TEMPLATE for the ASC webhook secrets file.
 *
 * The REAL file is named `asc-webhook-secrets.php` and lives ABOVE the web root
 * on the TransIP server (in the spookwerknl home dir, alongside www/), NOT in
 * this repo and NOT inside www/. It must be chmod 600 and is never web-served.
 *
 * Deploy (from a machine with the SSH alias configured):
 *   scp hooks/asc-webhook-secrets.example.php \
 *       spookw.ssh.transip.me:asc-webhook-secrets.php   # then edit values + chmod 600
 *
 * asc.php loads it via:  dirname($_SERVER['DOCUMENT_ROOT']) . '/asc-webhook-secrets.php'
 */

return [
    // The same secret string you enter in App Store Connect → Manage webhooks.
    'asc_webhook_secret' => 'REPLACE_WITH_ASC_WEBHOOK_SECRET',

    // Dedicated, send-only Pushover application token (pushover.net/apps/build).
    'pushover_app_token' => 'REPLACE_WITH_PUSHOVER_APP_TOKEN',

    // Olaf's Pushover user key.
    'pushover_user_key'  => 'REPLACE_WITH_PUSHOVER_USER_KEY',
];
