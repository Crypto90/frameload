<?php
// POST /api/v1/icon.php {"package": "a.b", "icon": "<base64 PNG/WebP/JPEG>"}: a listed game's icon,
// kept only when it has none yet (first upload wins). Same limits as an icon sent with a report.
declare(strict_types=1);
require __DIR__ . '/../../../app/bootstrap.php';

if (($_SERVER['REQUEST_METHOD'] ?? '') === 'OPTIONS') {
    header('Access-Control-Allow-Origin: *');
    header('Access-Control-Allow-Methods: POST, OPTIONS');
    header('Access-Control-Allow-Headers: Content-Type');
    exit;
}
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    json_out(['ok' => false, 'error' => 'POST a JSON body with package and icon'], 405);
}
$max = 1024 + 4 * intdiv(ICON_MAX_BYTES + 2, 3);
$raw = file_get_contents('php://input', false, null, 0, $max + 1);
if ($raw === false || strlen($raw) > $max) {
    json_out(['ok' => false, 'error' => 'too large'], 413);
}
$in = json_decode($raw, true);
$package = is_array($in) ? (string)($in['package'] ?? '') : '';
if (!valid_package($package)) {
    json_out(['ok' => false, 'error' => 'invalid package'], 422);
}
$error = accept_icon_upload(db(), $package, $in['icon'] ?? null, hmac('ip:' . client_ip()));
if ($error !== '') {
    $status = str_starts_with($error, 'too many') ? 429 : (str_contains($error, 'already') ? 409 : 422);
    json_out(['ok' => false, 'error' => $error], $status);
}
json_out(['ok' => true, 'icon' => icon_url($package)]);
