<?php
// Game icons: the launcher icon FrameLoad took from each game's APK, uploaded once per game.
// Stored outside the document root and served by public/icon.php.
declare(strict_types=1);

const ICON_DIR = DATA_DIR . '/icons';
const ICON_SIZE = 128;            // re-encoded to this square size when GD is available
const ICON_MAX_BYTES = 262144;    // what an upload may be before decoding
const ICON_TYPES = [IMAGETYPE_PNG => 'png', IMAGETYPE_WEBP => 'webp', IMAGETYPE_JPEG => 'jpg'];

function icon_file(string $package): ?string
{
    if (!valid_package($package)) {
        return null;
    }
    foreach (ICON_TYPES as $ext) {
        $path = ICON_DIR . "/$package.$ext";
        if (is_file($path)) {
            return $path;
        }
    }
    return null;
}

function icon_url(string $package): ?string
{
    $file = icon_file($package);
    return $file ? '/icon.php?package=' . rawurlencode($package) . '&v=' . filemtime($file) : null;
}

/**
 * Stores a game's first icon. Returns '' on success, else why it was refused.
 * Only an image of a plausible icon shape is kept; with GD it is decoded and written anew as a PNG,
 * so nothing but pixels survives.
 */
function save_icon(string $package, string $bytes): string
{
    if (!valid_package($package)) {
        return 'invalid package';
    }
    if (icon_file($package)) {
        return 'this game already has an icon';
    }
    if ($bytes === '' || strlen($bytes) > ICON_MAX_BYTES) {
        return 'the icon must be an image of at most 256 KB';
    }
    $info = @getimagesizefromstring($bytes);
    if (!$info || !isset(ICON_TYPES[$info[2]])) {
        return 'the icon must be a PNG, WebP or JPEG image';
    }
    [$w, $h] = $info;
    if ($w < 48 || $h < 48 || $w > 1024 || $h > 1024 || abs($w - $h) > max($w, $h) * 0.1) {
        return 'the icon must be roughly square, 48 to 1024 pixels';
    }
    if (!is_dir(ICON_DIR)) {
        mkdir(ICON_DIR, 0750, true);
    }
    $target = ICON_DIR . "/$package.png";
    if (function_exists('imagecreatefromstring')) {
        $src = @imagecreatefromstring($bytes);
        if (!$src) {
            return 'the image could not be read';
        }
        $dst = imagecreatetruecolor(ICON_SIZE, ICON_SIZE);
        imagealphablending($dst, false);
        imagesavealpha($dst, true);
        imagefill($dst, 0, 0, imagecolorallocatealpha($dst, 0, 0, 0, 127));
        imagecopyresampled($dst, $src, 0, 0, 0, 0, ICON_SIZE, ICON_SIZE, $w, $h);
        $tmp = $target . '.tmp';
        $ok = imagepng($dst, $tmp, 9);
        if (!$ok || !rename($tmp, $target)) {
            @unlink($tmp);
            return 'the icon could not be stored';
        }
        return '';
    }
    // Without GD the validated original is kept, under the extension of what it really is.
    $target = ICON_DIR . "/$package." . ICON_TYPES[$info[2]];
    return file_put_contents($target, $bytes, LOCK_EX) === false ? 'the icon could not be stored' : '';
}

/** Rate limit shared by both ways of uploading: true when this address may upload one more. */
function icon_upload_allowed(PDO $pdo, string $ipHash): bool
{
    $pdo->exec('CREATE TABLE IF NOT EXISTS icon_uploads (ip_hash TEXT NOT NULL, created_at INTEGER NOT NULL)');
    $stmt = $pdo->prepare('SELECT COUNT(*) FROM icon_uploads WHERE ip_hash = ? AND created_at >= ?');
    $stmt->execute([$ipHash, time() - 3600]);
    return (int)$stmt->fetchColumn() < (int)config()['icon_uploads_per_hour_per_ip'];
}

function note_icon_upload(PDO $pdo, string $ipHash): void
{
    $pdo->prepare('INSERT INTO icon_uploads (ip_hash, created_at) VALUES (?, ?)')->execute([$ipHash, time()]);
}

/** An icon sent with a report or on its own: base64 in JSON. '' when stored, else why not. */
function accept_icon_upload(PDO $pdo, string $package, mixed $encoded, string $ipHash): string
{
    if (!is_string($encoded) || $encoded === '') {
        return 'no icon';
    }
    if (icon_file($package)) {
        return 'this game already has an icon';
    }
    $exists = $pdo->prepare('SELECT 1 FROM games WHERE package = ?');
    $exists->execute([$package]);
    if (!$exists->fetchColumn()) {
        return 'only listed games get an icon';
    }
    if (!icon_upload_allowed($pdo, $ipHash)) {
        return 'too many icons, try later';
    }
    $bytes = base64_decode($encoded, true);
    if ($bytes === false) {
        return 'the icon must be base64';
    }
    $error = save_icon($package, $bytes);
    if ($error === '') {
        note_icon_upload($pdo, $ipHash);
    }
    return $error;
}
