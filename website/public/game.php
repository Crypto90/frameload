<?php
declare(strict_types=1);
require __DIR__ . '/../app/bootstrap.php';
require __DIR__ . '/../app/layout.php';

$package = (string)($_GET['package'] ?? '');
$game = valid_package($package) ? (games_with_status([$package])[$package] ?? null) : null;
if (!$game) {
    http_response_code(404);
    page_start('Game not found', 'This game is not on the FrameLoad compatibility list.');
    echo '<section class="wrap page-narrow"><h1>Not on the list yet</h1><p class="muted">Nobody has reported this game. <a href="/#compatibility">Back to the compatibility list</a>.</p></section>';
    page_end();
    exit;
}

$recent = db()->prepare(<<<SQL
    SELECT version_code, version_name, outcome, rating, duration, drew, fps, auto_fix, scale, refresh_rate, foveation,
           frameload_version, created_at
    FROM reports WHERE package = ? ORDER BY id DESC LIMIT 25
SQL);
$recent->execute([$package]);
$recent = $recent->fetchAll();

const OUTCOME_TEXT = [
    'quit' => 'Closed normally', 'stopped_player' => 'Stopped by the player', 'stopped_frameload' => 'Stopped by FrameLoad',
    'closed_by_steam' => 'Closed from Steam', 'start_failed' => 'Could not start', 'closed_early' => 'Closed right after starting',
    'crashed' => 'Crashed', 'gpu_hang' => 'Graphics processor hung', 'out_of_memory' => 'Ran out of memory',
    'guard_memory' => 'Stopped: memory', 'guard_frozen' => 'Froze', 'interrupted' => 'Headset restarted',
];

function minutes(int $seconds): string
{
    return $seconds >= 120 ? intdiv($seconds, 60) . ' min' : $seconds . ' s';
}

$settings = settings_text($game['settings']);
page_start($game['title'], "{$game['title']} on the Steam Frame: " . STATUSES[$game['status']]['label'] . '. ' . ($game['note'] ?: ''), 'compat');
?>
<section class="wrap game-page">
  <a class="back" href="/#compatibility">← Compatibility list</a>
  <div class="game-head">
    <?= game_avatar($game['package'], $game['title'], true) ?>
    <div>
      <h1><?= h($game['title']) ?></h1>
      <p class="muted mono"><?= h($game['package']) ?><?= $game['engine'] ? ' · ' . h($game['engine']) : '' ?></p>
    </div>
    <div class="game-status"><?= status_pill($game['status']) ?></div>
  </div>

  <div class="grid-2">
    <article class="card">
      <h2>On the Steam Frame</h2>
      <p><?= h($game['note'] ?: STATUSES[$game['status']]['blurb']) ?></p>
      <?php if ($settings): ?>
        <h3>Best settings</h3>
        <ul class="tags tags-block"><?php foreach ($settings as $s): ?><li class="tag"><?= h($s) ?></li><?php endforeach; ?></ul>
        <p class="muted small">Set them in FrameLoad: the game's page, then Settings.</p>
      <?php endif; ?>
      <?php if ($game['tested_at']): ?>
        <p class="muted small">Team test <?= h(date('j M Y', $game['tested_at'])) ?> with FrameLoad <?= h($game['tested_frameload']) ?><?= $game['tested_version'] ? ', game version ' . h($game['tested_version']) : '' ?>.</p>
      <?php endif; ?>
    </article>
    <article class="card">
      <h2>Community reports</h2>
      <?php if ($game['reports']): ?>
        <div class="breakdown">
          <?php foreach (['working', 'partial', 'broken'] as $k): ?>
            <div class="bar-row">
              <span><?= h(STATUSES[$k]['label']) ?></span>
              <span class="bar"><i class="v-<?= $k ?>" style="width: <?= round(100 * $game['votes'][$k] / max(1, $game['reports'])) ?>%"></i></span>
              <span class="num"><?= $game['votes'][$k] ?></span>
            </div>
          <?php endforeach; ?>
        </div>
        <p class="muted small"><?= $game['reports'] ?> headset<?= $game['reports'] === 1 ? '' : 's' ?> in the last 120 days<?= $game['fps'] ? ', about ' . $game['fps'] . ' fps' : '' ?>. With three or more, the reports decide the status.</p>
      <?php else: ?>
        <p class="muted">No reports yet. Play it with <em>Share compatibility reports</em> turned on in FrameLoad, and your session counts here.</p>
      <?php endif; ?>
    </article>
  </div>

  <?php if ($recent): ?>
  <article class="card">
    <h2>Recent sessions</h2>
    <div class="sessions" role="table" aria-label="Recent sessions">
      <div class="srow srow-head" role="row"><span role="columnheader">Rating</span><span role="columnheader">How it ended</span><span role="columnheader">Played</span><span role="columnheader">Settings</span><span role="columnheader">FrameLoad</span><span role="columnheader">When</span></div>
      <?php foreach ($recent as $r): ?>
        <div class="srow" role="row">
          <span role="cell"><?= status_pill($r['rating']) ?></span>
          <span role="cell"><?= h(OUTCOME_TEXT[$r['outcome']] ?? $r['outcome']) ?><?= $r['auto_fix'] === 'foveation_off' ? ' · foveation turned off' : '' ?></span>
          <span role="cell"><?= h(minutes((int)$r['duration'])) ?><?= $r['fps'] ? ' · ' . round((float)$r['fps']) . ' fps' : '' ?></span>
          <span role="cell" class="muted"><?= h(implode(', ', array_filter([
              $r['scale'] && (float)$r['scale'] !== 1.0 ? $r['scale'] . 'x' : '',
              $r['refresh_rate'] ? $r['refresh_rate'] . ' Hz' : '',
              $r['foveation'] && $r['foveation'] !== 'gaze' ? 'foveation ' . $r['foveation'] : '',
          ])) ?: 'defaults') ?></span>
          <span role="cell" class="muted"><?= h($r['frameload_version']) ?></span>
          <span role="cell" class="muted"><?= h(relative_time((int)$r['created_at'])) ?></span>
        </div>
      <?php endforeach; ?>
    </div>
  </article>
  <?php endif; ?>
</section>
<?php page_end();
