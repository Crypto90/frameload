<?php
// How a session report becomes a rating, and reports become a game's status.
declare(strict_types=1);

// Outcomes FrameLoad's session records use (frameload/manager/sessions.py).
const NORMAL_ENDS = ['quit', 'stopped_player', 'stopped_frameload', 'closed_by_steam'];
const FAILED_STARTS = ['start_failed', 'closed_early', 'could_not_start'];
const KNOWN_OUTCOMES = [
    'quit', 'stopped_player', 'stopped_frameload', 'closed_by_steam', 'start_failed', 'closed_early',
    'crashed', 'gpu_hang', 'out_of_memory', 'guard_memory', 'guard_frozen', 'interrupted',
];
const REPORT_WINDOW = 120 * 86400; // reports older than this no longer count
const MIN_PLAY_SECONDS = 120;      // a working session showed its picture at least this long

/** One session: working, partial or broken. */
function rate_report(string $outcome, int $duration, bool $drew, string $autoFix): string
{
    if (in_array($outcome, FAILED_STARTS, true) || !$drew) {
        return $duration >= 300 && !in_array($outcome, FAILED_STARTS, true) ? 'partial' : 'broken';
    }
    if (in_array($outcome, NORMAL_ENDS, true) && $duration >= MIN_PLAY_SECONDS && $autoFix === '') {
        return 'working';
    }
    if (in_array($outcome, NORMAL_ENDS, true) && $duration < MIN_PLAY_SECONDS) {
        return 'partial';
    }
    return $duration >= 60 || $autoFix !== '' ? 'partial' : 'broken';
}

/** A game's status from its reports: each headset's latest report counts once. */
function status_from_votes(array $votes): string
{
    $total = array_sum($votes);
    if ($total === 0) {
        return 'untested';
    }
    if ($votes['working'] / $total >= 0.6) {
        return 'working';
    }
    if ($votes['broken'] / $total >= 0.6) {
        return 'broken';
    }
    return 'partial';
}

/** Every listed game with its status; $packages limits the list. */
function games_with_status(?array $packages = null): array
{
    $pdo = db();
    $where = '';
    $args = [];
    if ($packages !== null) {
        if (!$packages) {
            return [];
        }
        $where = 'WHERE g.package IN (' . implode(',', array_fill(0, count($packages), '?')) . ')';
        $args = array_values($packages);
    }
    $since = time() - REPORT_WINDOW;
    // The latest report of each headset per game.
    $sql = <<<SQL
        SELECT g.*, r.rating, r.created_at AS reported_at, r.fps, r.frameload_version
        FROM games g
        LEFT JOIN (
            SELECT package, install_hash, MAX(id) AS id FROM reports WHERE created_at >= $since
            GROUP BY package, install_hash
        ) latest ON latest.package = g.package
        LEFT JOIN reports r ON r.id = latest.id
        $where
    SQL;
    $stmt = $pdo->prepare($sql);
    $stmt->execute($args);
    $games = [];
    foreach ($stmt as $row) {
        $pkg = $row['package'];
        if (!isset($games[$pkg])) {
            $games[$pkg] = [
                'package' => $pkg,
                'title' => $row['title'],
                'engine' => $row['engine'],
                'curated' => $row['curated_status'],
                'note' => $row['curated_note'],
                'settings' => json_decode($row['curated_settings'] ?: '{}', true) ?: [],
                'tested_version' => $row['curated_version'],
                'tested_frameload' => $row['curated_frameload'],
                'tested_at' => $row['curated_at'] ? (int)$row['curated_at'] : null,
                'votes' => ['working' => 0, 'partial' => 0, 'broken' => 0],
                'last_report' => null,
                'fps' => [],
            ];
        }
        if ($row['rating']) {
            $games[$pkg]['votes'][$row['rating']]++;
            $games[$pkg]['last_report'] = max((int)$games[$pkg]['last_report'], (int)$row['reported_at']);
            if ($row['fps']) {
                $games[$pkg]['fps'][] = (float)$row['fps'];
            }
        }
    }
    foreach ($games as &$game) {
        $community = status_from_votes($game['votes']);
        $game['community'] = $community;
        $game['reports'] = array_sum($game['votes']);
        // A maintainer's test stands until reports say otherwise; with reports, they decide.
        $game['status'] = $game['reports'] >= 3 ? $community : ($game['curated'] ?: $community);
        $game['fps'] = $game['fps'] ? round(array_sum($game['fps']) / count($game['fps'])) : null;
        $game['updated'] = max((int)$game['tested_at'], (int)$game['last_report']) ?: null;
    }
    unset($game);
    uasort($games, fn($a, $b) => strcasecmp($a['title'], $b['title']));
    return $games;
}

function settings_text(array $settings): array
{
    $out = [];
    if (isset($settings['foveation']) && $settings['foveation'] === 'off') {
        $out[] = 'Foveated rendering: Off';
    }
    if (isset($settings['gpu_driver'], GPU_DRIVER_LABELS[$settings['gpu_driver']])) {
        $out[] = 'Graphics ' . lcfirst(GPU_DRIVER_LABELS[$settings['gpu_driver']]);
    }
    if (!empty($settings['scale']) && (float)$settings['scale'] !== 1.0) {
        $out[] = 'Resolution ' . rtrim(rtrim(number_format((float)$settings['scale'], 2), '0'), '.') . 'x';
    }
    if (!empty($settings['refresh_rate'])) {
        $out[] = (int)$settings['refresh_rate'] . ' Hz';
    }
    if (!empty($settings['min_frameload'])) {
        $out[] = 'FrameLoad ' . $settings['min_frameload'] . ' or newer';
    }
    return $out;
}
