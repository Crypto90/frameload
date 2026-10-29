<?php
declare(strict_types=1);
require __DIR__ . '/../app/bootstrap.php';
require __DIR__ . '/../app/layout.php';

$op = operator();
$address = array_filter([$op['name'], $op['street'], $op['city'], $op['country']]);
$email = $op['email'] !== '' ? '<a href="mailto:' . h($op['email']) . '">' . h($op['email']) . '</a>' : '–';
$hoster = $op['hoster'] !== '' ? h($op['hoster']) : '';
$logDays = max(1, (int)$op['log_days']);
$keepDays = REPORT_KEEP_DAYS;
$updated = '29.10.2026';

page_start('Datenschutz', 'Privacy policy of frameload.crypto90.de: what the site and the compatibility list process, and your rights.', 'legal');
?>
<section class="wrap page-narrow doc legal">
  <h1>Datenschutzerklärung</h1>
  <p class="lead">Stand: <?= h($updated) ?> · <a href="#english">English version below</a></p>
  <?php if (!operator_ready()): ?>
  <p class="legal-missing">Die Angaben zum Verantwortlichen fehlen noch: Name, Anschrift und E-Mail werden in <code>config.php</code> unter <code>operator</code> eingetragen.</p>
  <?php endif; ?>

  <h2>1. Verantwortlicher</h2>
  <p><?= implode('<br>', array_map('h', $address)) ?><br>E-Mail: <?= $email ?></p>

  <h2>2. Kurz gesagt</h2>
  <ul>
    <li>Diese Seite setzt <strong>keine Cookies</strong>, nutzt <strong>kein Tracking</strong> und keine Analysedienste und lädt nichts von Dritten nach: Schriften, Bilder und Skripte kommen von diesem Server.</li>
    <li>FrameLoad sendet Sitzungsberichte nur, wenn Sie das in der App einschalten (Einstellung „Share compatibility reports“, ab Werk aus). Sie enthalten keinen Namen, kein Konto, keine Steam-ID und keine Protokolle.</li>
    <li>IP-Adressen und die Kennung Ihres Headsets speichern wir nur als kryptografischen Hash (HMAC); den Hash der IP-Adresse löschen wir nach 24 Stunden, Berichte nach <?= $keepDays ?> Tagen.</li>
  </ul>

  <h2>3. Aufruf der Webseite und Server-Logdateien</h2>
  <p>Beim Aufruf jeder Seite verarbeitet der Webserver technisch notwendige Daten: IP-Adresse, Datum und Uhrzeit, aufgerufene Adresse, übertragene Datenmenge, Statuscode, Browser-Kennung (User-Agent) und die zuvor besuchte Seite (Referrer). Sie dienen der Auslieferung der Seite, ihrer Sicherheit und der Abwehr von Missbrauch. Rechtsgrundlage ist Art. 6 Abs. 1 lit. f DSGVO (berechtigtes Interesse an einem sicheren und funktionsfähigen Angebot). Die Logdateien werden nach <?= $logDays ?> Tagen gelöscht.</p>

  <h2>4. Hosting</h2>
  <p>Die Seite wird <?= $hoster !== '' ? 'bei ' . $hoster : 'bei einem Hosting-Anbieter in Deutschland' ?> betrieben. Der Anbieter verarbeitet die Daten in unserem Auftrag auf Grundlage eines Vertrags nach Art. 28 DSGVO und nur nach unseren Weisungen. Eine Übermittlung in Länder außerhalb der EU findet nicht statt.</p>

  <h2>5. Kompatibilitätsliste: Berichte aus FrameLoad</h2>
  <p>Wenn Sie in FrameLoad „Share compatibility reports“ einschalten, sendet das Headset nach jeder beendeten Spielsitzung einen Bericht an diese Seite. Er enthält:</p>
  <ul>
    <li>das Spiel (Paketname, Titel, Version, Engine) und, solange die Liste keines hat, sein Symbol;</li>
    <li>wie die Sitzung endete, ihr Ende (Zeitpunkt), ihre Dauer, ob ein Bild gezeigt wurde, die Bildrate und eine automatische Korrektur durch FrameLoad;</li>
    <li>die verwendeten Einstellungen (Auflösung, Bildwiederholrate, Foveated Rendering, Grafiktreiber-Workaround) und ob das Spiel FrameBridge enthält;</li>
    <li>die Versionen von FrameLoad, SteamOS und Lepton;</li>
    <li>eine zufällige Kennung, die FrameLoad einmal auf dem Headset erzeugt. Wir speichern sie nur als HMAC; sie dient dazu, die letzte Sitzung jedes Headsets einmal zu zählen.</li>
  </ul>
  <p>Ihre IP-Adresse speichern wir nur als HMAC, um die Zahl der Berichte pro Stunde zu begrenzen; dieser Wert wird nach 24 Stunden gelöscht. Berichte werden nach <?= $keepDays ?> Tagen gelöscht. Veröffentlicht werden nur zusammengefasste Ergebnisse je Spiel und Version (Status, Anzahl, empfohlene Einstellungen), nie einzelne Berichte.</p>
  <p>Zweck ist eine Liste, welche Spiele auf der Steam Frame laufen und mit welchen Einstellungen. Rechtsgrundlage ist Ihre Einwilligung durch das Einschalten der Einstellung (Art. 6 Abs. 1 lit. a DSGVO), die Sie jederzeit widerrufen können, indem Sie sie in FrameLoad ausschalten; die bis dahin erfolgte Verarbeitung bleibt rechtmäßig. Die Begrenzung pro Stunde beruht auf Art. 6 Abs. 1 lit. f DSGVO (Schutz vor Missbrauch).</p>

  <h2>6. Abruf der Liste durch FrameLoad</h2>
  <p>FrameLoad lädt die ganze Liste höchstens alle sechs Stunden, ohne mitzuteilen, welche Spiele installiert sind. Dabei fallen nur die Server-Logdaten nach Abschnitt 3 an.</p>

  <h2>7. Links zu anderen Seiten</h2>
  <p>Links zu GitHub und Ko-fi führen zu Angeboten anderer Anbieter. Erst wenn Sie einem Link folgen, erhält der jeweilige Anbieter Daten; dort gilt dessen Datenschutzerklärung.</p>

  <h2>8. Ihre Rechte</h2>
  <p>Sie haben das Recht auf Auskunft (Art. 15 DSGVO), Berichtigung (Art. 16), Löschung (Art. 17), Einschränkung der Verarbeitung (Art. 18), Datenübertragbarkeit (Art. 20) und Widerspruch gegen Verarbeitungen nach Art. 6 Abs. 1 lit. f (Art. 21) sowie auf Widerruf einer Einwilligung (Art. 7 Abs. 3). Schreiben Sie dazu an <?= $email ?>. Da wir Berichte nur unter dem Hash Ihrer Headset-Kennung speichern, können wir sie Ihnen nur zuordnen, wenn Sie uns diese Kennung nennen (Art. 11 DSGVO); sie steht in FrameLoads <code>config.json</code> unter <code>compat.install_id</code>.</p>
  <p>Sie haben außerdem das Recht, sich bei einer Datenschutz-Aufsichtsbehörde zu beschweren (Art. 77 DSGVO), insbesondere in dem Bundesland Ihres Wohnorts oder unseres Sitzes.</p>

  <h2>9. Pflicht zur Bereitstellung</h2>
  <p>Sie müssen keine Daten bereitstellen. Ohne Berichte funktioniert FrameLoad ganz normal; die Seite lässt sich ohne Angaben nutzen.</p>

  <hr id="english">
  <h1>Privacy policy</h1>
  <p class="lead">Last updated <?= h($updated) ?>. The German version above is binding.</p>

  <h2>1. Controller</h2>
  <p><?= implode('<br>', array_map('h', $address)) ?><br>Email: <?= $email ?></p>

  <h2>2. In short</h2>
  <ul>
    <li>No cookies, no tracking, no analytics, nothing loaded from third parties: fonts, pictures and scripts come from this server.</li>
    <li>FrameLoad sends session reports only when you switch them on in the app ("Share compatibility reports", off by default). They contain no name, account, Steam ID or logs.</li>
    <li>IP addresses and your headset's id are stored only as cryptographic hashes (HMAC); the address hash is deleted after 24 hours, reports after <?= $keepDays ?> days.</li>
  </ul>

  <h2>3. Visiting the site and server logs</h2>
  <p>For every page the web server processes the data needed to deliver it: IP address, date and time, the address requested, the amount of data, the status code, the browser's user agent and the referring page, to deliver the site, keep it secure and stop abuse (Art. 6 (1) (f) GDPR, legitimate interest). The logs are deleted after <?= $logDays ?> days.</p>

  <h2>4. Hosting</h2>
  <p>The site is hosted <?= $hoster !== '' ? 'by ' . $hoster : 'by a hosting provider in Germany' ?>, which processes data on our behalf under a contract according to Art. 28 GDPR. No data is transferred outside the EU.</p>

  <h2>5. Compatibility list: reports from FrameLoad</h2>
  <p>With "Share compatibility reports" on, the headset sends one report after each finished game session: the game (package name, title, version, engine, and its icon while the list has none), how the session ended, its end time and length, whether it showed a picture, its frame rate, any automatic fix, the settings it ran with (resolution, refresh rate, foveated rendering, graphics driver workaround), whether it contains FrameBridge, the versions of FrameLoad, SteamOS and Lepton, and a random id FrameLoad created once on the headset, stored here only as an HMAC so each headset's latest session counts once. Your IP address is stored only as an HMAC to limit reports per hour and is deleted after 24 hours; reports are deleted after <?= $keepDays ?> days. Only aggregated results per game and version are published, never single reports. Legal basis: your consent by switching the setting on (Art. 6 (1) (a) GDPR), which you can withdraw at any time by switching it off; the hourly limit rests on Art. 6 (1) (f) GDPR.</p>

  <h2>6. FrameLoad reading the list</h2>
  <p>FrameLoad downloads the whole list at most every six hours without saying which games are installed; only the server logs of section 3 arise.</p>

  <h2>7. Links</h2>
  <p>Links to GitHub and Ko-fi lead to other providers, who receive data only when you follow the link; their privacy policies apply there.</p>

  <h2>8. Your rights</h2>
  <p>You have the right of access (Art. 15 GDPR), rectification (16), erasure (17), restriction (18), data portability (20), objection to processing under Art. 6 (1) (f) (21) and to withdraw consent (7 (3)); write to <?= $email ?>. Because reports are stored only under the hash of your headset's id, we can find yours only if you give us that id (Art. 11 GDPR): it is <code>compat.install_id</code> in FrameLoad's <code>config.json</code>. You may also lodge a complaint with a data protection supervisory authority (Art. 77 GDPR).</p>

  <h2>9. No obligation</h2>
  <p>You do not have to provide any data. FrameLoad works normally without reports, and the site needs no input from you.</p>
</section>
<?php page_end();
