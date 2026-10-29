<?php
declare(strict_types=1);
require __DIR__ . '/../app/bootstrap.php';
require __DIR__ . '/../app/layout.php';

$op = operator();
$address = array_filter([$op['name'], $op['street'], $op['city'], $op['country']]);

page_start('Impressum', 'Legal notice of frameload.crypto90.de (Impressum according to § 5 DDG).', 'legal');
?>
<section class="wrap page-narrow doc legal">
  <h1>Impressum</h1>
  <p class="lead">Angaben gemäß § 5 Digitale-Dienste-Gesetz (DDG) · <a href="#english">English version below</a></p>
  <?php if (!operator_ready()): ?>
  <p class="legal-missing">Die Angaben zum Betreiber fehlen noch: Name, Anschrift und E-Mail werden in <code>config.php</code> unter <code>operator</code> eingetragen.</p>
  <?php endif; ?>

  <h2>Diensteanbieter</h2>
  <p><?= implode('<br>', array_map('h', $address)) ?></p>

  <h2>Kontakt</h2>
  <p>
    E-Mail: <?= $op['email'] !== '' ? '<a href="mailto:' . h($op['email']) . '">' . h($op['email']) . '</a>' : '–' ?>
    <?php if ($op['phone'] !== ''): ?><br>Telefon: <?= h($op['phone']) ?><?php endif; ?>
  </p>

  <h2>Verantwortlich für den Inhalt nach § 18 Abs. 2 MStV</h2>
  <p><?= h($op['responsible'] !== '' ? $op['responsible'] : $op['name']) ?>, Anschrift wie oben.</p>

  <h2>Verbraucherstreitbeilegung</h2>
  <p>Wir sind nicht bereit oder verpflichtet, an Streitbeilegungsverfahren vor einer Verbraucherschlichtungsstelle teilzunehmen.</p>

  <h2>Haftung für Inhalte</h2>
  <p>Die Inhalte dieser Seite werden mit Sorgfalt erstellt. Die Kompatibilitätsliste beruht auf eigenen Tests und auf automatisch übermittelten Berichten von FrameLoad-Nutzern; für ihre Richtigkeit, Vollständigkeit und Aktualität übernehmen wir keine Gewähr. Als Diensteanbieter sind wir nach den allgemeinen Gesetzen für eigene Inhalte verantwortlich; für fremde, übermittelte Informationen gelten die §§ 7 bis 10 DDG. Sobald uns eine Rechtsverletzung bekannt wird, entfernen wir den betreffenden Inhalt umgehend.</p>

  <h2>Haftung für Links</h2>
  <p>Diese Seite verlinkt auf Seiten Dritter (zum Beispiel GitHub und Ko-fi), auf deren Inhalte wir keinen Einfluss haben. Für diese Inhalte ist der jeweilige Anbieter verantwortlich. Bei Bekanntwerden von Rechtsverletzungen entfernen wir den Link umgehend.</p>

  <h2>Urheberrecht und Marken</h2>
  <p>FrameLoad ist ein unabhängiges Projekt und steht in keiner Verbindung zu Valve oder Meta. Steam, Steam Frame und SteamVR sind Marken der Valve Corporation; Meta Quest ist eine Marke von Meta Platforms, Inc. Spielenamen und Spielesymbole gehören ihren jeweiligen Rechteinhabern und dienen nur der Kennzeichnung des Spiels. Rechteinhaber, die ein Symbol entfernt haben möchten, erreichen uns unter der oben genannten E-Mail-Adresse.</p>

  <hr id="english">
  <h1>Legal notice</h1>
  <p class="lead">Information according to § 5 of the German Digital Services Act (DDG). The German version above is binding.</p>

  <h2>Service provider</h2>
  <p><?= implode('<br>', array_map('h', $address)) ?></p>

  <h2>Contact</h2>
  <p>
    Email: <?= $op['email'] !== '' ? '<a href="mailto:' . h($op['email']) . '">' . h($op['email']) . '</a>' : '–' ?>
    <?php if ($op['phone'] !== ''): ?><br>Phone: <?= h($op['phone']) ?><?php endif; ?>
  </p>

  <h2>Responsible for the content (§ 18 (2) MStV)</h2>
  <p><?= h($op['responsible'] !== '' ? $op['responsible'] : $op['name']) ?>, address as above.</p>

  <h2>Consumer dispute resolution</h2>
  <p>We are neither willing nor obliged to take part in dispute resolution proceedings before a consumer arbitration board.</p>

  <h2>Liability for content and links</h2>
  <p>The compatibility list is based on our own tests and on reports sent automatically by FrameLoad users; we give no guarantee that it is correct, complete or current. Pages of others that we link to (for example GitHub and Ko-fi) are the responsibility of their providers. We remove content or links as soon as we learn that they infringe the law.</p>

  <h2>Copyright and trademarks</h2>
  <p>FrameLoad is an independent project, not affiliated with Valve or Meta. Steam, Steam Frame and SteamVR are trademarks of Valve Corporation; Meta Quest is a trademark of Meta Platforms, Inc. Game names and icons belong to their owners and only identify the game. Owners who want an icon removed can reach us at the email address above.</p>
</section>
<?php page_end();
