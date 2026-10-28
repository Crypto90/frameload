<?php
declare(strict_types=1);
require __DIR__ . '/../app/bootstrap.php';
require __DIR__ . '/../app/layout.php';

$example = json_encode([
    'install_id' => '7f3c9a2e-41d8-4b6e-9c0a-2f5e8d1b7a64',
    'package' => 'com.VerticalRobot.RedMatter2',
    'title' => 'Red Matter 2',
    'version_code' => '75',
    'version_name' => '1.0.021',
    'engine' => 'Unreal',
    'outcome' => 'stopped_player',
    'session_end' => 1793193571,
    'duration' => 153,
    'drew' => true,
    'fps' => 72.2,
    'auto_fix' => '',
    'settings' => ['scale' => 1.0, 'refresh_rate' => 0, 'foveation' => 'off', 'gpu_driver' => 'sysmem'],
    'framebridge' => true,
    'frameload_version' => '1.4.4',
    'os_build' => '20261007.6125817',
    'lepton' => '3.0.5 (rootfs 3.0.3)',
], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);

page_start('Reporting API', 'How FrameLoad reports game sessions to the compatibility list, and how to read it.', 'api');
?>
<section class="wrap page-narrow doc">
  <h1>Reporting API</h1>
  <p class="lead">The compatibility list is built from session reports. FrameLoad sends one after each game session when the player has turned on <strong>Share compatibility reports</strong>. Reading the list is open to everyone.</p>

  <h2>Read: <code>GET /api/v1/compat.php</code></h2>
  <p>Every listed game, or only some with <code>?packages=com.a.game,com.b.game</code> (up to 500). Each entry has <code>status</code> (<code>working</code>, <code>partial</code>, <code>broken</code>, <code>untested</code>), the team's <code>note</code> and recommended <code>settings</code> learnt from reports: for each version code (<code>settings_by_version</code>) the foveation and graphics driver settings whose sessions went best, each headset's latest session per settings counting once; a hang, crash or freeze counts against the settings it ran with. Settings need at least two headsets that played well with them; until then <code>settings_source</code> is <code>team</code>, else <code>reports</code>. <code>status_by_version</code> has each version code's own status and headset count; once three headsets played the newest version, it decides <code>status</code> (<code>status_version</code> names it), and FrameLoad shows an installed version's own status once three headsets played it. FrameLoad applies <code>foveation</code>, <code>gpu_driver</code>, <code>hide_space_warp</code> and <code>stable_local</code> under the player's own, for its installed version first. Each entry also has the <code>votes</code> of headsets.</p>
  <pre><code>curl https://frameload.crypto90.de/api/v1/compat.php?packages=com.VerticalRobot.RedMatter2</code></pre>

  <h2>Report: <code>POST /api/v1/report.php</code></h2>
  <p>JSON body, at most 8 KB plus an optional <code>icon</code>. <code>install_id</code> is a random id the headset makes once; the site keeps only its HMAC. Required: <code>install_id</code>, <code>package</code>, <code>outcome</code> and <code>session_end</code> (Unix time, within the last 30 days). The same session (install, package, end) counts once.</p>
  <pre><code><?= h($example) ?></code></pre>
  <p><code>outcome</code> is one of FrameLoad's session outcomes: <code><?= h(implode('</code>, <code>', KNOWN_OUTCOMES)) ?></code>.</p>

  <h2>Icons: <code>POST /api/v1/icon.php</code></h2>
  <p><code>{"package": "…", "icon": "&lt;base64&gt;"}</code>: a PNG, WebP or JPEG of at most 256 KB, roughly square, 48 to 1024 pixels. Only a game already on the list gets one, and only its first icon is kept; it is stored as a fresh 128 × 128 PNG. A report may carry the same <code>icon</code> field; FrameLoad sends the game's launcher icon that way while the list shows none (<code>icon</code> is <code>null</code> in <code>compat.php</code>).</p>

  <h2>How a session is rated</h2>
  <ul>
    <li><strong>Working</strong>: it showed its picture, ran at least two minutes and ended normally, without FrameLoad having to change a setting.</li>
    <li><strong>Partial</strong>: it played but crashed, froze or hung later, ended within two minutes, or FrameLoad had to change a setting for it.</li>
    <li><strong>Not working</strong>: it could not start or never showed a picture.</li>
  </ul>
  <p>A game's status counts each headset's latest session of the last 120 days: 60 % or more working is Working, 60 % or more not working is Not working, anything else is Partial. Until three headsets have reported, the team's own test stands.</p>

  <h2>Limits</h2>
  <p><?= (int)config()['reports_per_hour_per_install'] ?> reports per hour per headset and <?= (int)config()['reports_per_hour_per_ip'] ?> per address. Answers: <code>200</code> with <code>rating</code> and the game's <code>status</code>; <code>422</code> for a report that does not validate; <code>429</code> when over the limit.</p>
</section>
<?php page_end();
