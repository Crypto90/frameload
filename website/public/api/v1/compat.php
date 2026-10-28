<?php
// GET /api/v1/compat.php[?packages=a.b,c.d]: the compatibility status of games, for FrameLoad's library
// badges and anyone else. Without packages: every listed game.
declare(strict_types=1);
require __DIR__ . '/../../../app/bootstrap.php';

$packages = null;
if (isset($_GET['packages'])) {
    $packages = array_values(array_filter(array_slice(explode(',', (string)$_GET['packages']), 0, 500), 'valid_package'));
}
$games = [];
foreach (games_with_status($packages) as $package => $game) {
    $games[$package] = [
        'title' => $game['title'],
        'status' => $game['status'],
        'label' => STATUSES[$game['status']]['label'],
        'note' => $game['note'],
        'settings' => (object)$game['settings'],
        'settings_text' => settings_text($game['settings']),
        'reports' => $game['reports'],
        'votes' => $game['votes'],
        'fps' => $game['fps'],
        'tested_version' => $game['tested_version'],
        'tested_frameload' => $game['tested_frameload'],
        'updated' => $game['updated'],
        'url' => (empty($_SERVER['HTTPS']) || $_SERVER['HTTPS'] === 'off' ? 'http://' : 'https://')
            . ($_SERVER['HTTP_HOST'] ?? 'frameload.crypto90.de') . '/game.php?package=' . rawurlencode($package),
    ];
}
json_out(['games' => $games, 'generated' => time()]);
