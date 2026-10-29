<?php
declare(strict_types=1);
require __DIR__ . '/../app/bootstrap.php';
require __DIR__ . '/../app/layout.php';

$games = games_with_status();
$counts = array_fill_keys(array_keys(STATUSES), 0);
$reports = 0;
foreach ($games as $game) {
    $counts[$game['status']]++;
    $reports += $game['reports'];
}

page_start('FrameLoad', 'Install and play Quest games and Android apps on the Valve Steam Frame, entirely on the headset. Community compatibility list included.', 'compat');
?>
<section class="hero">
  <div class="hero-bg" aria-hidden="true"><img src="/assets/img/hero.jpg" alt="" width="1376" height="768" fetchpriority="high"></div>
  <div class="wrap hero-inner">
    <p class="eyebrow">For the Valve Steam Frame</p>
    <h1>Your Quest library,<br><span class="grad">on the Steam Frame.</span></h1>
    <p class="lead">FrameLoad installs, ports and launches Quest games and Android apps right inside the headset. No PC, no phone, no cable: browse, download and play from one window in VR.</p>
    <div class="hero-actions">
      <a class="btn btn-primary" href="#compatibility">See what runs</a>
      <a class="btn btn-ghost" href="#install">Install FrameLoad</a>
    </div>
    <dl class="stats">
      <div><dt>Games tracked</dt><dd><?= count($games) ?></dd></div>
      <div><dt>Working</dt><dd class="ok"><?= $counts['working'] ?></dd></div>
      <div><dt>Community reports</dt><dd><?= $reports ?></dd></div>
    </dl>
  </div>
</section>

<section class="features wrap" aria-label="Features">
  <article class="feature">
    <div class="feature-icon" aria-hidden="true">⬇</div>
    <h2>Install in the headset</h2>
    <p>Browse the catalog, download and install with the controller. OBB data, install scripts and Steam artwork are handled for you.</p>
  </article>
  <article class="feature">
    <div class="feature-icon" aria-hidden="true">⚙</div>
    <h2>Tuned for the Frame</h2>
    <p>Per-game resolution, refresh rate and foveation. Games that hang the graphics processor get fixed settings automatically, and the settings that worked for other players apply before a game's first start.</p>
  </article>
  <article class="feature">
    <div class="feature-icon" aria-hidden="true">✚</div>
    <h2>Knows what went wrong</h2>
    <p>Every crash or freeze gets a plain-language explanation and a full log, ready to share.</p>
  </article>
</section>

<section id="compatibility" class="compat wrap">
  <div class="section-head">
    <div>
      <h2>Compatibility list</h2>
      <p class="muted">Tested by the FrameLoad team and rated from anonymous session reports of headsets that share them. Each headset's latest session counts once.</p>
    </div>
  </div>

  <div class="toolbar" role="search">
    <label class="search">
      <span class="sr-only">Search games</span>
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10.5 3a7.5 7.5 0 0 1 5.96 12.06l4.24 4.24-1.42 1.42-4.24-4.24A7.5 7.5 0 1 1 10.5 3Zm0 2a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11Z"/></svg>
      <input id="search" type="search" placeholder="Search by game or package" autocomplete="off">
    </label>
    <label class="sort-menu">
      <span>Sort by</span>
      <select id="sort-menu">
        <option value="">Recommended order</option>
        <option value="title-asc">Game, A to Z</option>
        <option value="title-desc">Game, Z to A</option>
        <option value="status-asc">Status, working first</option>
        <option value="status-desc">Status, not working first</option>
        <option value="reports-desc">Most reports</option>
        <option value="reports-asc">Fewest reports</option>
        <option value="note-asc">Notes, A to Z</option>
      </select>
    </label>
    <div class="chips" role="group" aria-label="Filter by status">
      <button class="chip" type="button" data-filter="all" aria-pressed="true">All <span><?= count($games) ?></span></button>
      <?php foreach (STATUSES as $key => $status): ?>
        <button class="chip chip-<?= h($key) ?>" type="button" data-filter="<?= h($key) ?>" aria-pressed="false"><?= h($status['label']) ?> <span><?= $counts[$key] ?></span></button>
      <?php endforeach; ?>
    </div>
  </div>

  <div class="table" id="games">
    <div class="row row-head" role="group" aria-label="Sort the list">
      <button type="button" class="sort" data-sort="title">Game</button>
      <button type="button" class="sort" data-sort="status">Status</button>
      <button type="button" class="sort" data-sort="note">Notes and best settings</button>
      <button type="button" class="sort" data-sort="reports">Reports</button>
    </div>
    <?php foreach ($games as $game): $settings = settings_text($game['settings']); ?>
      <a class="row game" href="/game.php?package=<?= h(rawurlencode($game['package'])) ?>"
         data-status="<?= h($game['status']) ?>" data-search="<?= h(strtolower($game['title'] . ' ' . $game['package'])) ?>"
         data-title="<?= h(strtolower($game['title'])) ?>" data-rank="<?= array_search($game['status'], array_keys(STATUSES), true) ?>"
         data-note="<?= h(strtolower($game['note'] ?: STATUSES[$game['status']]['blurb'])) ?>"
         data-reports="<?= (int)$game['reports'] ?>" data-tested="<?= (int)($game['tested_at'] ?? 0) ?>">
        <span class="game-id">
          <?= game_avatar($game['package'], $game['title']) ?>
          <span><strong><?= h($game['title']) ?></strong><small><?= h($game['package']) ?></small></span>
        </span>
        <span><?= status_pill($game['status']) ?></span>
        <span class="notes">
          <?= h($game['note'] ?: STATUSES[$game['status']]['blurb']) ?>
          <?php if ($settings): ?><span class="tags"><?php foreach ($settings as $s): ?><span class="tag"><?= h($s) ?></span><?php endforeach; ?></span><?php endif; ?>
        </span>
        <span class="reports">
          <?php if ($game['reports']): ?>
            <span class="votes" title="<?= h("{$game['votes']['working']} working, {$game['votes']['partial']} partial, {$game['votes']['broken']} not working") ?>">
              <?php foreach (['working', 'partial', 'broken'] as $k): if ($game['votes'][$k]): ?>
                <i class="v-<?= $k ?>" style="flex: <?= $game['votes'][$k] ?>"></i>
              <?php endif; endforeach; ?>
            </span>
            <small><?= $game['reports'] ?> report<?= $game['reports'] === 1 ? '' : 's' ?></small>
          <?php else: ?>
            <small class="muted">Team test<?= $game['tested_at'] ? ' · ' . h(relative_time($game['tested_at'])) : '' ?></small>
          <?php endif; ?>
        </span>
      </a>
    <?php endforeach; ?>
    <p class="empty" id="empty" hidden>No game matches. Played one that is missing? Turn on <em>Share compatibility reports</em> in FrameLoad and it appears here after your next session.</p>
  </div>
</section>

<section id="install" class="install wrap">
  <div class="install-card">
    <div>
      <h2>Install FrameLoad</h2>
      <p class="muted">On the Steam Frame, switch to Desktop Mode, open Konsole and run:</p>
      <div class="code">
        <code id="install-cmd"><?= h(INSTALL_COMMAND) ?></code>
        <button class="btn btn-small btn-primary" type="button" data-copy="#install-cmd">Copy</button>
      </div>
      <p class="muted small">Then start FrameLoad from your Steam library. It updates itself from inside the headset.</p>
    </div>
    <img class="install-shot" src="/assets/img/library.jpg" alt="FrameLoad's library view in the headset" width="1600" height="900" loading="lazy">
  </div>
</section>

<section class="share wrap">
  <h2>Help the list grow</h2>
  <p class="muted">In FrameLoad, open <strong>System</strong> and turn on <strong>Share compatibility reports</strong>. After each session your headset sends how it went: the game, how long it ran, whether it showed its picture, how it ended and the settings it used. No name, account or log is sent, and the site keeps your headset's random id and your connection's address only as one-way hashes (the address just to stop abuse). The <a href="/api.php">reporting API</a> is open.</p>
</section>
<?php page_end();
