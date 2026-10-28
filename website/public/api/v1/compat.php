<?php
// GET /api/v1/compat.php[?packages=a.b,c.d]: the compatibility status of games, for FrameLoad's library
// badges and anyone else. Without packages: every listed game.
declare(strict_types=1);
require __DIR__ . '/../../../app/bootstrap.php';

$packages = null;
if (isset($_GET['packages'])) {
    $packages = array_values(array_filter(array_slice(explode(',', (string)$_GET['packages']), 0, 500), 'valid_package'));
}
$base = (empty($_SERVER['HTTPS']) || $_SERVER['HTTPS'] === 'off' ? 'http://' : 'https://')
    . ($_SERVER['HTTP_HOST'] ?? 'frameload.crypto90.de');
$games = [];
foreach (games_with_status($packages) as $package => $game) {
    $games[$package] = [
        'title' => $game['title'],
        'status' => $game['status'],
        'label' => STATUSES[$game['status']]['label'],
        'note' => $game['note'],
        'settings' => (object)$game['settings'],
        // Per version code, each headset's latest session of it counting once; status_version names the version
        // the status is about when enough headsets played the newest one.
        'status_by_version' => (object)$game['status_by_version'],
        'status_version' => $game['status_version'],
        'settings_text' => settings_text($game['settings']),
        // Learnt from reports for each version code ("team" when the team's test still stands).
        'settings_by_version' => (object)array_map(fn($s) => (object)$s, $game['settings_by_version']),
        'settings_source' => $game['settings_source'],
        'reports' => $game['reports'],
        'votes' => $game['votes'],
        'fps' => $game['fps'],
        'tested_version' => $game['tested_version'],
        'tested_frameload' => $game['tested_frameload'],
        'updated' => $game['updated'],
        'icon' => ($icon = icon_url($package)) ? $base . $icon : null,
        'url' => $base . '/game.php?package=' . rawurlencode($package),
    ];
}
json_out(['games' => $games, 'generated' => time()]);
