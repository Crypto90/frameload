<?php
// Copy to config.php (next to public/, never inside it) and set your own secret.
return [
    // Install ids and addresses are stored only as HMACs keyed with this. Any long random string:
    //   php -r 'echo bin2hex(random_bytes(32)), "\n";'
    'secret' => 'replace-with-a-long-random-string',
    // 'db_path' => __DIR__ . '/data/frameload.sqlite',
    // 'reports_per_hour_per_ip' => 120,
    // 'reports_per_hour_per_install' => 60,
];
