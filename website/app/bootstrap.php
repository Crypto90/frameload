<?php
// FrameLoad website: shared setup for every page and API endpoint.
declare(strict_types=1);

const APP_DIR = __DIR__;
const DATA_DIR = __DIR__ . '/../data';
const GITHUB_URL = 'https://github.com/Crypto90/frameload';
const KOFI_URL = 'https://ko-fi.com/K3K314GUP';
const INSTALL_COMMAND = 'curl -fsSLO https://github.com/Crypto90/frameload/releases/latest/download/frameload-installer.sh && bash frameload-installer.sh';

// Statuses, best first. "untested": listed, but nobody has reported it yet.
const STATUSES = [
    'working' => ['label' => 'Working', 'blurb' => 'Starts, shows its picture and plays normally.'],
    'partial' => ['label' => 'Partial', 'blurb' => 'Plays, but with problems: a crash or hang later, or it needs a setting changed.'],
    'broken'  => ['label' => 'Not working', 'blurb' => 'Does not start or never shows a picture on the Steam Frame.'],
    'untested' => ['label' => 'Untested', 'blurb' => 'No report yet.'],
];

function config(): array
{
    static $config = null;
    if ($config === null) {
        $file = APP_DIR . '/../config.php';
        $config = array_merge([
            'db_path' => DATA_DIR . '/frameload.sqlite',
            // Install ids and addresses are stored only as HMACs with this secret. Set your own in config.php.
            'secret' => 'change-me',
            'reports_per_hour_per_ip' => 120,
            'reports_per_hour_per_install' => 60,
            'icon_uploads_per_hour_per_ip' => 40,
        ], is_file($file) ? (require $file) : []);
    }
    return $config;
}

function db(): PDO
{
    static $pdo = null;
    if ($pdo instanceof PDO) {
        return $pdo;
    }
    $path = config()['db_path'];
    $fresh = !is_file($path);
    if (!is_dir(dirname($path))) {
        mkdir(dirname($path), 0750, true);
    }
    $pdo = new PDO('sqlite:' . $path, null, null, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]);
    $pdo->exec('PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON; PRAGMA busy_timeout = 4000;');
    migrate($pdo);
    if ($fresh) {
        require_once APP_DIR . '/seed.php';
        seed_curated($pdo);
    }
    return $pdo;
}

function migrate(PDO $pdo): void
{
    $pdo->exec(<<<SQL
        CREATE TABLE IF NOT EXISTS games (
            package TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            engine TEXT NOT NULL DEFAULT '',
            curated_status TEXT,
            curated_note TEXT NOT NULL DEFAULT '',
            curated_settings TEXT NOT NULL DEFAULT '{}',
            curated_version TEXT NOT NULL DEFAULT '',
            curated_frameload TEXT NOT NULL DEFAULT '',
            curated_at INTEGER,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            package TEXT NOT NULL REFERENCES games(package),
            version_code TEXT NOT NULL DEFAULT '',
            version_name TEXT NOT NULL DEFAULT '',
            install_hash TEXT NOT NULL,
            ip_hash TEXT NOT NULL,
            session_end INTEGER NOT NULL,
            outcome TEXT NOT NULL,
            rating TEXT NOT NULL,
            duration INTEGER NOT NULL DEFAULT 0,
            drew INTEGER NOT NULL DEFAULT 0,
            fps REAL,
            auto_fix TEXT NOT NULL DEFAULT '',
            scale REAL,
            refresh_rate INTEGER,
            foveation TEXT NOT NULL DEFAULT '',
            framebridge INTEGER NOT NULL DEFAULT 0,
            frameload_version TEXT NOT NULL DEFAULT '',
            os_build TEXT NOT NULL DEFAULT '',
            lepton TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            UNIQUE (install_hash, package, session_end)
        );
        CREATE INDEX IF NOT EXISTS reports_package ON reports (package, created_at);
        CREATE INDEX IF NOT EXISTS reports_ip ON reports (ip_hash, created_at);
    SQL);
}

function h(?string $text): string
{
    return htmlspecialchars((string)$text, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function hmac(string $value): string
{
    return hash_hmac('sha256', $value, config()['secret']);
}

function client_ip(): string
{
    return $_SERVER['REMOTE_ADDR'] ?? '0.0.0.0';
}

function valid_package(string $package): bool
{
    return (bool)preg_match('/^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$/', $package) && strlen($package) <= 200;
}

function json_out(array $data, int $status = 200): never
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    header('Access-Control-Allow-Origin: *');
    echo json_encode($data, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

function relative_time(?int $time): string
{
    if (!$time) {
        return '';
    }
    $diff = time() - $time;
    if ($diff < 3600) {
        return max(1, intdiv($diff, 60)) . ' min ago';
    }
    if ($diff < 86400) {
        return intdiv($diff, 3600) . ' h ago';
    }
    if ($diff < 86400 * 60) {
        return intdiv($diff, 86400) . ' days ago';
    }
    return date('M Y', $time);
}

require_once APP_DIR . '/status.php';
require_once APP_DIR . '/icons.php';
