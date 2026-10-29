# FrameLoad website

The site at **https://frameload.crypto90.de**: a landing page, the community compatibility list, a page per
game, and the reporting API FrameLoad uses (`frameload/manager/compat_reports.py`).

Plain PHP 8.1+ with SQLite (PDO). No framework, no build step, no database server, no third-party requests.

```
website/
├── public/            ← the web server's document root
│   ├── index.php      landing page + compatibility list
│   ├── game.php       one game: status, best settings, reports, recent sessions
│   ├── api.php        API documentation
│   ├── api/v1/report.php   POST one session report
│   ├── api/v1/compat.php   GET statuses (all, or ?packages=a,b)
│   └── assets/        CSS, JS, images
├── app/               code outside the document root (bootstrap, rating rules, seed list, layout)
├── data/              the SQLite database (created on the first request)
└── config.sample.php  copy to config.php
```

## Deploy

1. Upload the whole `website/` folder, and point the domain's document root at `website/public`.
   `app/`, `data/` and `config.php` must stay outside the document root (they also carry
   `Require all denied` for Apache in case they end up inside it).
2. `cp config.sample.php config.php` and set `secret` to a long random string
   (`php -r 'echo bin2hex(random_bytes(32)), "\n";'`). Install ids and addresses are stored only as HMACs with it.
3. Make `data/` writable by PHP. The database and the team's test results (`app/seed.php`) are created
   on the first request.
4. Needs the `pdo_sqlite` extension. HTTPS is expected; FrameLoad talks to `https://frameload.crypto90.de`.
5. Fill in `operator` in `config.php`: name, postal address, email (and, if you like, phone), the hosting
   provider and how many days the web server keeps its access logs. The legal notice (`/impressum.php`, § 5 DDG)
   and the privacy policy (`/datenschutz.php`, GDPR) read them from there, so they never reach the repository; until
   they are filled in, both pages show a warning. Set the web server's access-log retention to the days you name.

## Legal pages and data kept

The site sets no cookies, has no tracking and loads nothing from third parties. Reports keep the headset's random
id and the sender's address only as HMACs; `purge_old_data()` (bootstrap.php, at most hourly from the report and icon
endpoints) blanks the address hash after 24 hours and deletes reports after `REPORT_KEEP_DAYS` (180; they stop
counting after 120). Change the privacy policy (`public/datenschutz.php`) whenever what the site processes changes.

On nginx, deny `app/`, `data/` and dotfiles yourself and add the headers from `public/.htaccess`.

Run it locally: `php -S 127.0.0.1:8099 -t website/public`.

## How the status is decided

A session is rated in `app/status.php` (FrameLoad shows the same rating, `compat_reports.rating`):
**working** when it showed its picture, ran at least 2 minutes and ended normally without FrameLoad changing
a setting; **not working** when it could not start or never showed a picture; **partial** otherwise.
A game's status counts each headset's latest session of the last 120 days (60 % decides). Until three
headsets have reported, the team's own test in `app/seed.php` stands.

To update the team's results, edit `CURATED` in `app/seed.php` and run once:
`php -r 'require "app/bootstrap.php"; require "app/seed.php"; seed_curated(db());'`
