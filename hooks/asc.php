<?php
/**
 * App Store Connect webhook receiver  →  Pushover relay
 *
 * Spookwerk / The Office task #333.
 * Design: The Office docs/superpowers/specs/2026-06-09-asc-webhook-pushover-relay-design.md
 *
 * Apple ASC POSTs a signed payload here when an app's review/version state
 * changes (APP_STORE_VERSION_STATE_CHANGED). We verify the HMAC-SHA256
 * signature, then relay a human-readable message to Pushover.
 *
 * This file is PUBLIC (committed to the public spookwerk.nl repo). It contains
 * NO secrets. Secrets live in a separate file ABOVE the web root, loaded at
 * runtime (see $secretsPath below) — never web-served, never committed.
 */

header('Content-Type: text/plain; charset=utf-8');

// ---- 0. Only accept POST -----------------------------------------------------
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    http_response_code(405);
    exit;
}

// ---- 1. Load secrets (from above docroot) ------------------------------------
// DOCUMENT_ROOT is .../spookwerknl/www ; its parent is the home dir, not served.
$secretsPath = dirname($_SERVER['DOCUMENT_ROOT']) . '/asc-webhook-secrets.php';
$logPath     = dirname($_SERVER['DOCUMENT_ROOT']) . '/asc-webhook.log';

$asc_log = function (string $line) use ($logPath) {
    // Best-effort; never fatal. (date() default TZ is fine for an ops log.)
    @file_put_contents($logPath, '[' . date('c') . '] ' . $line . "\n", FILE_APPEND | LOCK_EX);
};

if (!is_readable($secretsPath)) {
    http_response_code(500);
    $asc_log('FATAL: secrets file not readable at ' . $secretsPath);
    exit;
}
/** @var array{asc_webhook_secret:string,pushover_app_token:string,pushover_user_key:string} $cfg */
$cfg = require $secretsPath;
foreach (['asc_webhook_secret', 'pushover_app_token', 'pushover_user_key'] as $k) {
    if (empty($cfg[$k])) {
        http_response_code(500);
        $asc_log('FATAL: missing config key ' . $k);
        exit;
    }
}

// ---- 2. Read RAW body (HMAC is over raw bytes) -------------------------------
$rawBody = file_get_contents('php://input');
if ($rawBody === false) { $rawBody = ''; }

// ---- 3. Verify X-Apple-SIGNATURE (HMAC-SHA256, constant-time) -----------------
// PHP exposes "X-Apple-SIGNATURE" as HTTP_X_APPLE_SIGNATURE.
// Apple sends it as "hmacsha256=<hexdigest>" — strip the algorithm prefix.
// (The digest is hex, which never contains '=', so splitting on the first '='
// is safe and yields the bare signature.)
$provided = trim($_SERVER['HTTP_X_APPLE_SIGNATURE'] ?? '');
if (($eqPos = strpos($provided, '=')) !== false) {
    $provided = substr($provided, $eqPos + 1);
}
$macRaw   = hash_hmac('sha256', $rawBody, $cfg['asc_webhook_secret'], true);
// Tolerate either hex or base64 encoding of the SAME HMAC — accepting both does
// not weaken security (both require the secret); it just avoids an encoding
// mismatch silently failing verification. We log which form matched so we can
// tighten to the exact one Apple uses after the first real delivery.
$expectHex = hash_hmac('sha256', $rawBody, $cfg['asc_webhook_secret']); // hex
$expectB64 = base64_encode($macRaw);

$sigOk = $provided !== '' && (
    hash_equals($expectHex, $provided) ||
    hash_equals($expectB64, $provided)
);

if (!$sigOk) {
    http_response_code(401);
    $asc_log('REJECT: bad/missing signature. provided=' . substr($provided, 0, 24)
        . '… bodylen=' . strlen($rawBody));
    exit;
}

// ---- 4. Parse payload (defensive — confirm exact shape on first delivery) -----
$payload  = json_decode($rawBody, true);
// Apple's envelope: { "data": { "type": "<camelCase>", "attributes": {...} } }.
// Ping deliveries have type "webhookPingCreated". Since this endpoint is
// subscribed to ONLY the APP_STORE_VERSION_STATE_CHANGED event, any non-ping
// delivery IS the state change we care about — so we don't need to match an
// exact (still-unconfirmed) camelCase type string. Ignore pings + empties.
$dataType = is_array($payload) ? (string) ($payload['data']['type'] ?? '') : '';

if ($dataType === '' || stripos($dataType, 'ping') !== false) {
    http_response_code(200);
    $asc_log('IGNORE type=' . $dataType);
    exit;
}

// Real (non-ping) state-change event. Log the raw body ONLY for these (rare)
// until the first one confirms Apple's exact attribute field names — then this
// line and the attribute-dump fallback below can be tightened/removed.
$asc_log('STATE-CHANGE raw=' . $rawBody);

// Best-effort field extraction for a useful message; fall back gracefully.
$dig = function (array $a, array $keys) {
    foreach ($keys as $path) {
        $cur = $a; $ok = true;
        foreach (explode('.', $path) as $seg) {
            if (is_array($cur) && array_key_exists($seg, $cur)) { $cur = $cur[$seg]; }
            else { $ok = false; break; }
        }
        if ($ok && (is_string($cur) || is_numeric($cur))) { return (string) $cur; }
    }
    return '';
};

$appName  = is_array($payload) ? $dig($payload, [
    'data.attributes.appName', 'appName', 'data.attributes.app.name', 'app.name',
]) : '';
$newState = is_array($payload) ? $dig($payload, [
    'data.attributes.newValue', 'data.attributes.appStoreState', 'newValue',
    'data.attributes.state', 'state',
]) : '';
$oldState = is_array($payload) ? $dig($payload, [
    'data.attributes.oldValue', 'oldValue', 'data.attributes.previousState',
]) : '';
$version  = is_array($payload) ? $dig($payload, [
    'data.attributes.versionString', 'versionString', 'data.attributes.version',
]) : '';

// ---- 5. Compose + send Pushover ----------------------------------------------
$titleApp = $appName !== '' ? $appName : 'App Store Connect';
$title    = $titleApp . ' — review state';

$bodyParts = [];
if ($version !== '')  { $bodyParts[] = 'v' . $version; }
if ($oldState !== '' && $newState !== '') {
    $bodyParts[] = $oldState . ' → ' . $newState;
} elseif ($newState !== '') {
    $bodyParts[] = $newState;
} else {
    // Field names not yet confirmed for the real event — dump the attributes
    // so the push is still useful. Tighten once we've seen one live transition.
    $attrs = (is_array($payload) && isset($payload['data']['attributes'])
        && is_array($payload['data']['attributes'])) ? $payload['data']['attributes'] : [];
    $compact = $attrs ? json_encode($attrs, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) : '';
    $bodyParts[] = ($compact && $compact !== '[]')
        ? substr($compact, 0, 800) : 'state changed (see log for payload)';
}
$message = implode('  ', $bodyParts);

$post = http_build_query([
    'token'    => $cfg['pushover_app_token'],
    'user'     => $cfg['pushover_user_key'],
    'title'    => $title,
    'message'  => $message,
    'priority' => '0',
]);

$ch = curl_init('https://api.pushover.net/1/messages.json');
curl_setopt_array($ch, [
    CURLOPT_POST           => true,
    CURLOPT_POSTFIELDS     => $post,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_TIMEOUT        => 10,
    CURLOPT_CONNECTTIMEOUT => 5,
]);
$resp     = curl_exec($ch);
$httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
$curlErr  = curl_error($ch);
curl_close($ch);

if ($resp === false || $httpCode < 200 || $httpCode >= 300) {
    // Apple gets a 200 regardless (the event WAS valid) — we don't want retries
    // hammering us when the failure is our Pushover leg. Log it for follow-up.
    $asc_log('PUSHOVER-FAIL http=' . $httpCode . ' err=' . $curlErr
        . ' resp=' . substr((string) $resp, 0, 300) . ' msg=' . $message);
} else {
    $asc_log('PUSHOVER-OK msg=' . $message);
}

http_response_code(200);
echo 'ok';
