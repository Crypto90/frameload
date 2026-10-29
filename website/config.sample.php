<?php
// Copy to config.php (next to public/, never inside it) and set your own secret.
return [
    // Install ids and addresses are stored only as HMACs keyed with this. Any long random string:
    //   php -r 'echo bin2hex(random_bytes(32)), "\n";'
    'secret' => 'replace-with-a-long-random-string',
    // 'db_path' => __DIR__ . '/data/frameload.sqlite',
    // 'reports_per_hour_per_ip' => 120,
    // 'reports_per_hour_per_install' => 60,

    // The legal notice (Impressum, § 5 DDG) and the privacy page (Datenschutz, GDPR) name who runs the site.
    // They stay out of the public repository: fill them in here, on the server.
    'operator' => [
        'name' => '',          // full name (or company)
        'street' => '',        // street and house number: a postal address, not a P.O. box
        'city' => '',          // postcode and city, e.g. '12345 Berlin'
        'country' => 'Deutschland',
        'email' => '',         // contact address that is read
        'phone' => '',         // optional
        'responsible' => '',   // optional: responsible for content (§ 18 (2) MStV), if not the operator
        'hoster' => '',        // hosting provider (name, address), named in the privacy page
        'log_days' => 7,       // days the web server keeps its access logs (set it to what the server does)
    ],
];
