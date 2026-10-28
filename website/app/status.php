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
const STATUS_MIN_HEADSETS = 3;     // headsets whose reports outvote the team's test, per game and per version
const SETTINGS_MIN_HEADSETS = 2;   // headsets that played well with settings before the site recommends them

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

// Settings FrameLoad reports and may recommend (frameload/manager/compat_reports.py RECOMMENDABLE), with the
// value that means "unchanged". A report from before a key existed ran with that value.
const SETTING_DEFAULTS = ['foveation' => 'gaze', 'gpu_driver' => 'default'];
// How a session speaks for the settings it ran with: a hang, crash or freeze is against them.
const AGAINST_SETTINGS = ['gpu_hang', 'crashed', 'guard_frozen', 'start_failed', 'closed_early', 'could_not_start'];

/** How well one session went with its settings: 1 good, 0 bad, 0.5 in between. */
function settings_score(string $outcome, string $rating, bool $drew): float
{
    if (!$drew || in_array($outcome, AGAINST_SETTINGS, true)) {
        return 0.0;
    }
    return $rating === 'working' ? 1.0 : 0.5;
}

/**
 * The best settings among those reported: [] when the unchanged settings do best, null without evidence.
 * Only settings that at least SETTINGS_MIN_HEADSETS headsets played well with count, so one odd report decides nothing.
 */
function best_settings(array $combos): ?array
{
    $default = implode('|', SETTING_DEFAULTS);
    $best = null;
    $bestScore = -1.0;
    foreach ($combos as $combo => [$sum, $n, $good]) {
        if ($good < SETTINGS_MIN_HEADSETS) {
            continue;
        }
        // One pseudo-session that went badly: a single good report counts less than several.
        $score = $sum / ($n + 1);
        if ($score > $bestScore || ($score === $bestScore && $combo === $default)) {
            [$best, $bestScore] = [$combo, $score];
        }
    }
    if ($best === null || $bestScore < 0.5) {
        return null;  // nothing has worked for enough headsets yet: the team's test stands
    }
    if ($best === $default) {
        return [];
    }
    $out = [];
    foreach (array_combine(array_keys(SETTING_DEFAULTS), explode('|', $best)) as $key => $value) {
        if ($value !== SETTING_DEFAULTS[$key]) {
            $out[$key] = $value;
        }
    }
    return $out;
}

/**
 * Recommended settings learnt from reports, per game: ['settings' => for the newest version with evidence,
 * 'by_version' => [version_code => settings]]. Each headset's latest session per version and settings counts once.
 */
function derived_settings(PDO $pdo, ?array $packages = null): array
{
    $since = time() - REPORT_WINDOW;
    $where = '';
    $args = [$since];
    if ($packages !== null) {
        $where = 'AND package IN (' . implode(',', array_fill(0, count($packages), '?')) . ')';
        $args = array_merge($args, array_values($packages));
    }
    $stmt = $pdo->prepare(<<<SQL
        SELECT r.package, r.version_code, r.foveation, r.gpu_driver, r.outcome, r.rating, r.drew
        FROM reports r JOIN (
            SELECT MAX(id) AS id FROM reports
            WHERE created_at >= ? AND foveation != '' $where
            GROUP BY package, version_code, install_hash, foveation, gpu_driver
        ) latest ON latest.id = r.id
    SQL);
    $stmt->execute($args);
    $combos = [];
    foreach ($stmt as $row) {
        $combo = $row['foveation'] . '|' . ($row['gpu_driver'] ?: SETTING_DEFAULTS['gpu_driver']);
        $cell = &$combos[$row['package']][$row['version_code']][$combo];
        $cell = $cell ?? [0.0, 0, 0];
        $score = settings_score($row['outcome'], $row['rating'], (bool)$row['drew']);
        $cell[0] += $score;
        $cell[1]++;
        $cell[2] += $score === 1.0 ? 1 : 0;
        unset($cell);
    }
    $out = [];
    foreach ($combos as $package => $versions) {
        $byVersion = [];
        foreach ($versions as $version => $versionCombos) {
            $best = best_settings($versionCombos);
            if ($best !== null) {
                $byVersion[(string)$version] = $best;
            }
        }
        if (!$byVersion) {
            continue;
        }
        uksort($byVersion, fn($a, $b) => (int)$b <=> (int)$a);  // newest version first
        $out[$package] = ['settings' => reset($byVersion), 'by_version' => $byVersion];
    }
    return $out;
}

/** Votes per game and version code (newest first): each headset's latest report of that version counts once. */
function version_votes(PDO $pdo, ?array $packages, int $since): array
{
    $where = '';
    $args = [$since];
    if ($packages !== null) {
        $where = 'AND package IN (' . implode(',', array_fill(0, count($packages), '?')) . ')';
        $args = array_merge($args, array_values($packages));
    }
    $stmt = $pdo->prepare(<<<SQL
        SELECT r.package, r.version_code, r.rating FROM reports r JOIN (
            SELECT MAX(id) AS id FROM reports WHERE created_at >= ? AND version_code != '' $where
            GROUP BY package, version_code, install_hash
        ) latest ON latest.id = r.id
    SQL);
    $stmt->execute($args);
    $out = [];
    foreach ($stmt as $row) {
        $votes = &$out[$row['package']][(string)$row['version_code']];
        $votes = $votes ?? ['working' => 0, 'partial' => 0, 'broken' => 0];
        $votes[$row['rating']]++;
        unset($votes);
    }
    foreach ($out as &$versions) {
        uksort($versions, fn($a, $b) => (int)$b <=> (int)$a);
    }
    unset($versions);
    return $out;
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
                'settings_by_version' => [],
                'settings_source' => $row['curated_settings'] && $row['curated_settings'] !== '{}' ? 'team' : '',
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
    $byVersion = version_votes($pdo, $packages, $since);
    foreach ($games as $pkg => &$game) {
        $community = status_from_votes($game['votes']);
        $game['community'] = $community;
        $game['reports'] = array_sum($game['votes']);
        // Each version on its own: an update can break a game that worked, or fix one that did not.
        $game['status_by_version'] = [];
        foreach ($byVersion[$pkg] ?? [] as $version => $votes) {
            $game['status_by_version'][(string)$version] = [
                'status' => status_from_votes($votes), 'reports' => array_sum($votes), 'votes' => $votes,
            ];
        }
        $newest = array_key_first($game['status_by_version']);
        $game['status_version'] = null;
        if ($newest !== null && $game['status_by_version'][$newest]['reports'] >= STATUS_MIN_HEADSETS) {
            // Enough headsets on the newest version: they decide.
            $game['status'] = $game['status_by_version'][$newest]['status'];
            $game['status_version'] = (string)$newest;
        } else {
            // A maintainer's test stands until reports say otherwise; with reports, they decide.
            $game['status'] = $game['reports'] >= STATUS_MIN_HEADSETS ? $community : ($game['curated'] ?: $community);
        }
        $game['fps'] = $game['fps'] ? round(array_sum($game['fps']) / count($game['fps'])) : null;
        $game['updated'] = max((int)$game['tested_at'], (int)$game['last_report']) ?: null;
    }
    unset($game);
    // Settings learnt from reports replace the team's once headsets have reported with them.
    foreach (derived_settings($pdo, $packages) as $pkg => $derived) {
        if (isset($games[$pkg])) {
            $games[$pkg]['settings'] = $derived['settings'];
            $games[$pkg]['settings_by_version'] = $derived['by_version'];
            $games[$pkg]['settings_source'] = 'reports';
        }
    }
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
