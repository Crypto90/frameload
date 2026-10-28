<?php
// POST /api/v1/report.php: one finished game session from a headset whose player turned on
// "Share compatibility reports" in FrameLoad. Nothing personal is sent; the random install id and
// the sender's address are stored only as HMACs, the address only for rate limiting.
declare(strict_types=1);
require __DIR__ . '/../../../app/bootstrap.php';

if (($_SERVER['REQUEST_METHOD'] ?? '') === 'OPTIONS') {
    header('Access-Control-Allow-Origin: *');
    header('Access-Control-Allow-Methods: POST, OPTIONS');
    header('Access-Control-Allow-Headers: Content-Type');
    exit;
}
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    json_out(['ok' => false, 'error' => 'POST a JSON report'], 405);
}
$raw = file_get_contents('php://input', false, null, 0, 8193);
if ($raw === false || strlen($raw) > 8192) {
    json_out(['ok' => false, 'error' => 'report too large'], 413);
}
$in = json_decode($raw, true);
if (!is_array($in)) {
    json_out(['ok' => false, 'error' => 'invalid JSON'], 400);
}

function field(array $in, string $key, string $pattern, string $default = ''): string
{
    $value = $in[$key] ?? $default;
    if (!is_string($value) && !is_int($value)) {
        return $default;
    }
    $value = trim((string)$value);
    return preg_match($pattern, $value) ? $value : $default;
}

$installId = field($in, 'install_id', '/^[A-Za-z0-9-]{16,64}$/');
$package = (string)($in['package'] ?? '');
$outcome = (string)($in['outcome'] ?? '');
if ($installId === '' || !valid_package($package) || !in_array($outcome, KNOWN_OUTCOMES, true)) {
    json_out(['ok' => false, 'error' => 'install_id, package and a known outcome are required'], 422);
}
$sessionEnd = (int)($in['session_end'] ?? 0);
if ($sessionEnd < time() - 30 * 86400 || $sessionEnd > time() + 3600) {
    json_out(['ok' => false, 'error' => 'session_end is not a recent time'], 422);
}

$pdo = db();
$installHash = hmac('install:' . $installId);
$ipHash = hmac('ip:' . client_ip());
$hour = time() - 3600;
$count = $pdo->prepare('SELECT COUNT(*) FROM reports WHERE ip_hash = ? AND created_at >= ?');
$count->execute([$ipHash, $hour]);
if ((int)$count->fetchColumn() >= config()['reports_per_hour_per_ip']) {
    json_out(['ok' => false, 'error' => 'too many reports, try later'], 429);
}
$count = $pdo->prepare('SELECT COUNT(*) FROM reports WHERE install_hash = ? AND created_at >= ?');
$count->execute([$installHash, $hour]);
if ((int)$count->fetchColumn() >= config()['reports_per_hour_per_install']) {
    json_out(['ok' => false, 'error' => 'too many reports, try later'], 429);
}

$duration = max(0, min(86400, (int)($in['duration'] ?? 0)));
$drew = !empty($in['drew']);
$fps = isset($in['fps']) && is_numeric($in['fps']) ? max(0.0, min(240.0, (float)$in['fps'])) : null;
$autoFix = field($in, 'auto_fix', '/^[a-z_]{0,40}$/');
$settings = is_array($in['settings'] ?? null) ? $in['settings'] : [];
$scale = isset($settings['scale']) && is_numeric($settings['scale']) ? max(0.5, min(2.0, (float)$settings['scale'])) : null;
$refresh = isset($settings['refresh_rate']) && in_array((int)$settings['refresh_rate'], [0, 72, 80, 90, 96, 108, 120, 144], true)
    ? (int)$settings['refresh_rate'] : null;
$foveation = in_array($settings['foveation'] ?? '', ['gaze', 'fixed', 'off'], true) ? $settings['foveation'] : '';
$title = mb_substr(trim(strip_tags((string)($in['title'] ?? ''))), 0, 120) ?: $package;
$engine = field($in, 'engine', '/^[A-Za-z0-9 ]{0,20}$/');
$rating = rate_report($outcome, $duration, $drew, $autoFix);

$pdo->beginTransaction();
// A report adds a game nobody listed yet; it never renames a listed one.
$pdo->prepare('INSERT OR IGNORE INTO games (package, title, engine, updated_at) VALUES (?, ?, ?, ?)')
    ->execute([$package, $title, $engine, time()]);
$stmt = $pdo->prepare(<<<SQL
    INSERT OR IGNORE INTO reports (package, version_code, version_name, install_hash, ip_hash, session_end, outcome,
        rating, duration, drew, fps, auto_fix, scale, refresh_rate, foveation, framebridge, frameload_version,
        os_build, lepton, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
SQL);
$stmt->execute([
    $package, field($in, 'version_code', '/^\d{1,20}$/'), mb_substr(field($in, 'version_name', '/^[\w.+\- ]{0,40}$/u'), 0, 40),
    $installHash, $ipHash, $sessionEnd, $outcome, $rating, $duration, $drew ? 1 : 0, $fps, $autoFix,
    $scale, $refresh, $foveation, !empty($in['framebridge']) ? 1 : 0,
    field($in, 'frameload_version', '/^\d+\.\d+\.\d+$/'), field($in, 'os_build', '/^[\w.\- ]{0,40}$/'),
    field($in, 'lepton', '/^[\w.() \-]{0,60}$/'), time(),
]);
$pdo->prepare('UPDATE games SET updated_at = ? WHERE package = ?')->execute([time(), $package]);
$pdo->commit();

$game = games_with_status([$package])[$package] ?? null;
json_out(['ok' => true, 'rating' => $rating, 'status' => $game['status'] ?? 'untested',
          'duplicate' => $stmt->rowCount() === 0]);
