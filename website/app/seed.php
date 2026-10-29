<?php
// The maintainers' own test results: the list's first entries, before any headset reports.
// Tested 2026-10-28 on a Steam Frame (SteamOS 0.4.5, Lepton 3.0.5) with FrameLoad 1.4.3; every game measured
// again on 2026-10-29 with FrameLoad 1.6.0 and the refresh rate under System set to 90 Hz (about 90 s each).
declare(strict_types=1);

const CURATED_TESTED_AT = '2026-10-29';
const CURATED_FRAMELOAD = '1.6.0';

const CURATED = [
    ['com.VerticalRobot.RedMatter', 'Red Matter', 'Unreal', 'working', '38',
     'Loads its 2.9 GB of data on the first start (about 75 s), then plays. With 1.3x resolution at 120 Hz it draws every second frame (60 fps).', []],
    ['com.VerticalRobot.RedMatter2', 'Red Matter 2', 'Unreal', 'working', '75',
     'With foveated rendering on, the graphics processor hung after about 40 s. With it off: a steady 90 fps at 90 Hz. FrameLoad turns it off by itself after a hang.',
     ['foveation' => 'off', 'min_frameload' => '1.4.2']],
    ['games.b4t.epicrollercoasters.oculus', 'Epic Roller Coasters', 'Unity', 'working', '6281',
     'The graphics processor hung when the main menu loaded (with foveated rendering on, and still sometimes with it off): the picture froze after the boot animation. With the graphics driver drawing straight to memory it passed the menu in three starts out of three. FrameLoad 1.5.0 applies these settings by itself. Ported as a Quest 3, it asks for 90 Hz and runs a steady 90 fps.',
     ['foveation' => 'off', 'gpu_driver' => 'sysmem', 'min_frameload' => '1.5.0']],
    ['com.camouflaj.salmon', "Marvel's Iron Man VR", 'Unity', 'working', '443305',
     'Steady 90 fps at 90 Hz. Needs its audio packs (Audio_<language>.obb), which FrameLoad installs since 1.4.1.',
     ['min_frameload' => '1.4.1']],
    ['com.iillusions.spacepiratetrainerquest', 'Space Pirate Trainer DX', 'Unity', 'working', '1979',
     'Steady 90 fps at 90 Hz.', []],
    ['com.poncle.vampiresurvivorsvr', 'Vampire Survivors VR', 'Unity', 'working', '717',
     'Steady 90 fps; it asks for 90 Hz itself. The first start loads for about 80 s.', []],
    ['com.MightyCoconut.WalkaboutMiniGolf', 'Walkabout Mini Golf', 'Unity', 'working', '60366',
     'Steady 90 fps at 90 Hz. The first start loads for about 80 s.', []],
    ['com.Zhes.RickAndMortyVR', 'Rick and Morty Virtual Rick-ality', 'Unity', 'working', '1',
     'Unofficial port. Needs its data folder, which FrameLoad installs since 1.4.1.', ['min_frameload' => '1.4.1']],
    ['com.gorillavr.oculus.triptovr', 'TriptoVR', 'Unity', 'working', '232',
     'Steady 90 fps at 90 Hz (it asks for 72 Hz). Its Steam shortcut had gone missing; FrameLoad 1.4.2 starts it anyway and restores the shortcut.', []],
    ['com.mechabit.quest.pierheadarcade2', 'Pierhead Arcade', 'Unity', 'working', '355', 'Steady 90 fps at 90 Hz.', []],
    ['com.parkline.wander', 'Wander', 'Unity', 'working', '3569', 'Steady 90 fps at 90 Hz.', []],
    ['com.EgerterSoftware.MovieDeckforPlex', 'Movie Deck for Plex', 'Unity', 'working', '61', 'Steady 90 fps at 90 Hz.', []],
    ['com.qcxr.qcxr', 'QuestCraft', 'Unity', 'working', '37', 'Plays.', []],
    ['com.picselica.OceanRiftFullQuest', 'Ocean Rift', 'Unity', 'partial', '73',
     'Steady 90 fps at 90 Hz, but the graphics processor hung once with foveated rendering on.', []],
    ['co.yomune.gargantua', 'SWORDS of GARGANTUA', 'Unreal', 'partial', '40007',
     "Runs with FrameLoad 1.5.4, whose FrameBridge fix ends the deadlock that kept it on its loading screen forever (SteamVR waits where Meta's runtime does not). With foveated rendering on, the graphics processor hung and took Steam down; with it off it plays at a steady 90 fps at 90 Hz. But SteamVR's OpenGL bridge inside the game leaks about six GPU buffers a frame (about 25 MB a second), so after about 5 minutes the headset runs short of memory and Freeze Guard stops the game before the headset freezes.",
     ['foveation' => 'off', 'min_frameload' => '1.5.4']],
    ['com.mrf.zephyrinteractive.planeinaroom', 'Plane In A Room (MR-Fix)', 'Unity', 'working', '200008',
     'Steady 90 fps at 90 Hz.', []],
    ['io.rc.gba', 'JUST HOOPS', 'Unity', 'working', '1105', 'Steady 90 fps at 90 Hz.', []],
    ['app.visionplayer', 'Vision Player Pro', 'Native', 'broken', '8',
     "Stops at start: it needs Android's network service discovery (NsdManager), which Lepton does not provide.", []],
    ['com.baldandbold.cinevoid', 'CineVoid - VR Media Player', 'Native', 'broken', '310',
     "Declares Android 14, which Lepton's Android 11 refuses to install; FrameLoad 1.6.0 ports it, which lowers that, and it installs. But it stops at start: it needs Android's USB service (UsbManager), which Lepton does not provide.",
     ['min_frameload' => '1.6.0']],
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
