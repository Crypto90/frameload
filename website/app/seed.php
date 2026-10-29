<?php
// The maintainers' own test results: the list's first entries, before any headset reports.
// Tested 2026-10-28 on a Steam Frame (SteamOS 0.4.5, Lepton 3.0.5) with FrameLoad 1.4.3.
declare(strict_types=1);

const CURATED_TESTED_AT = '2026-10-28';
const CURATED_FRAMELOAD = '1.4.3';

const CURATED = [
    ['com.VerticalRobot.RedMatter', 'Red Matter', 'Unreal', 'working', '38',
     'Loads its 2.9 GB of data on the first start (about 75 s), then plays.', []],
    ['com.VerticalRobot.RedMatter2', 'Red Matter 2', 'Unreal', 'working', '75',
     'With foveated rendering on, the graphics processor hung after about 40 s. With it off: a steady 72 fps. FrameLoad turns it off by itself after a hang.',
     ['foveation' => 'off', 'min_frameload' => '1.4.2']],
    ['games.b4t.epicrollercoasters.oculus', 'Epic Roller Coasters', 'Unity', 'working', '6281',
     'The graphics processor hung when the main menu loaded (with foveated rendering on, and still sometimes with it off): the picture froze after the boot animation. With the graphics driver drawing straight to memory it passed the menu at a steady 72 fps in three starts out of three. FrameLoad 1.5.0 applies these settings by itself.',
     ['foveation' => 'off', 'gpu_driver' => 'sysmem', 'min_frameload' => '1.5.0']],
    ['com.camouflaj.salmon', "Marvel's Iron Man VR", 'Unity', 'working', '443305',
     'Steady 72 fps. Needs its audio packs (Audio_<language>.obb), which FrameLoad installs since 1.4.1.',
     ['min_frameload' => '1.4.1']],
    ['com.iillusions.spacepiratetrainerquest', 'Space Pirate Trainer DX', 'Unity', 'working', '1979',
     'Steady 72 fps.', []],
    ['com.poncle.vampiresurvivorsvr', 'Vampire Survivors VR', 'Unity', 'working', '717',
     'Plays; first start loads for about 80 s.', []],
    ['com.MightyCoconut.WalkaboutMiniGolf', 'Walkabout Mini Golf', 'Unity', 'working', '60366',
     'Plays; first start loads for about 80 s.', []],
    ['com.Zhes.RickAndMortyVR', 'Rick and Morty Virtual Rick-ality', 'Unity', 'working', '1',
     'Unofficial port. Needs its data folder, which FrameLoad installs since 1.4.1.', ['min_frameload' => '1.4.1']],
    ['com.gorillavr.oculus.triptovr', 'TriptoVR', 'Unity', 'working', '232',
     'Plays. Its Steam shortcut had gone missing; FrameLoad 1.4.2 starts it anyway and restores the shortcut.', []],
    ['com.mechabit.quest.pierheadarcade2', 'Pierhead Arcade', 'Unity', 'working', '355', 'Plays.', []],
    ['com.parkline.wander', 'Wander', 'Unity', 'working', '3569', 'Steady 72 fps.', []],
    ['com.EgerterSoftware.MovieDeckforPlex', 'Movie Deck for Plex', 'Unity', 'working', '61', 'Steady 72 fps.', []],
    ['com.qcxr.qcxr', 'QuestCraft', 'Unity', 'working', '37', 'Plays.', []],
    ['com.picselica.OceanRiftFullQuest', 'Ocean Rift', 'Unity', 'partial', '73',
     'Steady 72 fps for minutes, but the graphics processor hung once with foveated rendering on.', []],
    ['co.yomune.gargantua', 'SWORDS of GARGANTUA', 'Unreal', 'partial', '40007',
     "Runs with FrameLoad 1.5.4, whose FrameBridge fix ends the deadlock that kept it on its loading screen forever (SteamVR waits where Meta's runtime does not). With foveated rendering on, the graphics processor hung and took Steam down; with it off it reached its title screen and played at about 65 fps, until the headset ran short of memory after 5 minutes and Freeze Guard stopped it.",
     ['foveation' => 'off', 'min_frameload' => '1.5.4']],
    ['app.visionplayer', 'Vision Player Pro', 'Native', 'broken', '8',
     "Stops at start: it needs Android's network service discovery (NsdManager), which Lepton does not provide.", []],
    ['xyz.skybox.player.ovr', 'SKYBOX VR Video Player', 'Unity', 'broken', '1644',
     'Checks its own signing certificate, so a ported copy stays on its loading screen.', []],
    ['com.portalVR.source', 'PortalVR', 'Native', 'broken', '1',
     'Installs completely with FrameLoad 1.4.3, but its Source engine stops at start: it needs "all files access", which Lepton cannot grant.',
     ['min_frameload' => '1.4.3']],
];

/** Changes whenever the list above does, so a site that is already running applies it again. */
function curated_hash(): string
{
    return md5(serialize([CURATED, CURATED_TESTED_AT, CURATED_FRAMELOAD]));
}

function seed_curated(PDO $pdo): void
{
    $at = strtotime(CURATED_TESTED_AT . ' 12:00 UTC');
    $stmt = $pdo->prepare(<<<SQL
        INSERT INTO games (package, title, engine, curated_status, curated_note, curated_settings,
                           curated_version, curated_frameload, curated_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(package) DO UPDATE SET title = excluded.title, engine = excluded.engine,
            curated_status = excluded.curated_status, curated_note = excluded.curated_note,
            curated_settings = excluded.curated_settings, curated_version = excluded.curated_version,
            curated_frameload = excluded.curated_frameload, curated_at = excluded.curated_at,
            updated_at = excluded.updated_at
    SQL);
    foreach (CURATED as [$package, $title, $engine, $status, $version, $note, $settings]) {
        $stmt->execute([$package, $title, $engine, $status, $note, json_encode($settings ?: new stdClass()),
                        $version, CURATED_FRAMELOAD, $at, $at]);
    }
}
