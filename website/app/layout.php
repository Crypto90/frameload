<?php
// Page frame shared by every HTML page.
declare(strict_types=1);

function page_start(string $title, string $description, string $active = ''): void
{
    $full = $title === 'FrameLoad' ? 'FrameLoad: games and apps for the Steam Frame' : "$title · FrameLoad";
    ?><!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title><?= h($full) ?></title>
<meta name="description" content="<?= h($description) ?>">
<meta property="og:title" content="<?= h($full) ?>">
<meta property="og:description" content="<?= h($description) ?>">
<meta property="og:image" content="/assets/img/hero.jpg">
<meta name="theme-color" content="#070b15">
<!-- The page is dark by design: browsers' automatic dark modes and Dark Reader leave it alone. -->
<meta name="color-scheme" content="dark only">
<meta name="supported-color-schemes" content="dark">
<meta name="darkreader-lock">
<script src="/assets/guard.js?v=2"></script>
<link rel="icon" href="/assets/img/favicon.png">
<link rel="stylesheet" href="/assets/site.css?v=2">
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="topbar">
  <div class="wrap topbar-inner">
    <a class="brand" href="/"><img src="/assets/img/icon-192.png" alt="" width="32" height="32"><span>FrameLoad</span></a>
    <nav class="nav" aria-label="Main">
      <a href="/#compatibility"<?= $active === 'compat' ? ' aria-current="page"' : '' ?>>Compatibility</a>
      <a href="/#install">Install</a>
      <a href="/api.php"<?= $active === 'api' ? ' aria-current="page"' : '' ?>>API</a>
      <a href="<?= h(GITHUB_URL) ?>" rel="noopener">GitHub</a>
    </nav>
    <a class="btn btn-small btn-ghost kofi" href="<?= h(KOFI_URL) ?>" rel="noopener">♥ Support</a>
  </div>
</header>
<main id="main">
<?php
}

function page_end(): void
{
    ?>
</main>
<footer class="footer">
  <div class="wrap footer-inner">
    <div>
      <div class="brand brand-small"><img src="/assets/img/icon-192.png" alt="" width="24" height="24"><span>FrameLoad</span></div>
      <p class="muted">Runs entirely on the Steam Frame. Not affiliated with Valve or Meta.</p>
    </div>
    <nav class="footer-links" aria-label="Footer">
      <a href="<?= h(GITHUB_URL) ?>" rel="noopener">GitHub</a>
      <a href="<?= h(GITHUB_URL) ?>/releases" rel="noopener">Releases</a>
      <a href="/api.php">Reporting API</a>
      <a href="<?= h(KOFI_URL) ?>" rel="noopener">Ko-fi</a>
    </nav>
  </div>
</footer>
<script src="/assets/site.js?v=1" defer></script>
</body>
</html>
<?php
}

function status_pill(string $status): string
{
    $label = STATUSES[$status]['label'] ?? $status;
    return '<span class="pill pill-' . h($status) . '"><i aria-hidden="true"></i>' . h($label) . '</span>';
}

function game_initials(string $title): string
{
    $words = preg_split('/[^A-Za-z0-9]+/', $title, -1, PREG_SPLIT_NO_EMPTY) ?: ['?'];
    return strtoupper(substr($words[0], 0, 1) . (isset($words[1]) ? substr($words[1], 0, 1) : ''));
}

function game_hue(string $package): int
{
    return hexdec(substr(md5($package), 0, 4)) % 360;
}
