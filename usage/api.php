<?php
declare(strict_types=1);

// Deployment keeps credentials and writable data above the public document root.
$secretsPath = dirname($_SERVER['DOCUMENT_ROOT']) . '/usage-secrets.php';
if (!is_file($secretsPath)) {
    http_response_code(500);
    exit;
}
require $secretsPath;

if (!defined('USAGE_WRITE_TOKEN') || !defined('USAGE_READ_TOKEN')) {
    http_response_code(500);
    exit;
}

$dataDir = defined('USAGE_DATA_DIR')
    ? USAGE_DATA_DIR
    : dirname($_SERVER['DOCUMENT_ROOT']) . '/usage-data';
$method = $_SERVER['REQUEST_METHOD'] ?? '';
$name = $_GET['name'] ?? '';
$validNames = ['bbcc', 'swcc', 'swst'];

if ($method === 'GET') {
    header('Cache-Control: no-store');
}

function emptyResponse(int $status): void
{
    http_response_code($status);
    exit;
}

function bearerToken(): ?string
{
    // Apache under CGI/FPM (shared hosting) drops the Authorization header from
    // $_SERVER unless CGIPassAuth is on; mod_rewrite re-exposes it under the
    // REDIRECT_ prefix and getallheaders() sees it when the SAPI does.
    $header = $_SERVER['HTTP_AUTHORIZATION']
        ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION']
        ?? (function_exists('getallheaders') ? (getallheaders()['Authorization'] ?? '') : '');
    if (!preg_match('/^Bearer (.+)$/', $header, $matches)) {
        return null;
    }
    return $matches[1];
}

function hasToken(string $expected): bool
{
    $provided = bearerToken();
    return $provided !== null && hash_equals($expected, $provided);
}

if ($method === 'POST') {
    if (!in_array($name, $validNames, true)) {
        emptyResponse(404);
    }
    if (!hasToken(USAGE_WRITE_TOKEN)) {
        emptyResponse(401);
    }

    // Read one byte past the limit so oversized requests are rejected without
    // allowing PHP to buffer an unbounded body in application memory.
    $input = fopen('php://input', 'rb');
    if ($input === false) {
        emptyResponse(400);
    }
    $body = stream_get_contents($input, 65537);
    if ($body === false || strlen($body) > 65536) {
        emptyResponse(400);
    }
    try {
        $decoded = json_decode($body, false, 512, JSON_THROW_ON_ERROR);
    } catch (JsonException) {
        emptyResponse(400);
    }
    if (!is_object($decoded)) {
        emptyResponse(400);
    }

    if (!is_dir($dataDir) && !mkdir($dataDir, 0700, true) && !is_dir($dataDir)) {
        emptyResponse(500);
    }
    $temporary = tempnam($dataDir, '.usage-');
    if ($temporary === false) {
        emptyResponse(500);
    }
    $target = $dataDir . DIRECTORY_SEPARATOR . $name . '.json';
    if (file_put_contents($temporary, $body, LOCK_EX) === false || !rename($temporary, $target)) {
        @unlink($temporary);
        emptyResponse(500);
    }
    chmod($target, 0600);
    emptyResponse(204);
}

if ($method === 'GET' && $name === 'all') {
    if (!hasToken(USAGE_READ_TOKEN)) {
        emptyResponse(401);
    }

    $result = [];
    foreach ($validNames as $account) {
        $path = $dataDir . DIRECTORY_SEPARATOR . $account . '.json';
        $data = null;
        $receivedAt = null;
        if (is_file($path)) {
            $contents = file_get_contents($path);
            if ($contents !== false) {
                try {
                    $value = json_decode($contents, false, 512, JSON_THROW_ON_ERROR);
                    if (is_object($value)) {
                        $data = $value;
                        $mtime = filemtime($path);
                        if ($mtime !== false) {
                            $receivedAt = gmdate('Y-m-d\TH:i:s\Z', $mtime);
                        }
                    }
                } catch (JsonException) {
                    // A partial/corrupt file is treated like missing data; POST's
                    // atomic rename makes this a defensive fallback only.
                }
            }
        }
        $result[$account] = ['received_at' => $receivedAt, 'data' => $data];
    }

    $encoded = json_encode($result, JSON_UNESCAPED_SLASHES);
    if ($encoded === false) {
        // Never let PHP's own error page answer; it can name the path.
        emptyResponse(500);
    }
    header('Content-Type: application/json');
    echo $encoded;
    exit;
}

emptyResponse(404);
