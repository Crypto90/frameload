<?php
// GET /icon.php?package=a.b: a game's icon (app/icons.php), cached by browsers for a week.
declare(strict_types=1);
require __DIR__ . '/../app/bootstrap.php';

$file = icon_file((string)($_GET['package'] ?? ''));
if (!$file) {
    http_response_code(404);
    header('Cache-Control: public, max-age=3600');
    exit;
}
$types = ['png' => 'image/png', 'webp' => 'image/webp', 'jpg' => 'image/jpeg'];
header('Content-Type: ' . $types[pathinfo($file, PATHINFO_EXTENSION)]);
header('Content-Length: ' . filesize($file));
header('Cache-Control: public, max-age=604800');
header('X-Content-Type-Options: nosniff');
header("Content-Security-Policy: default-src 'none'");
readfile($file);
