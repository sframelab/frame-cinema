# Third-party notices and credits

Sources, credits and license terms for Frame Cinema 0.5.20. This file also
ships with the app as `THIRD-PARTY-NOTICES.md`. License texts are in
`release/licenses/` in the repository, `licenses/` in the installed app, and
beside the components listed below.

Third-party parts keep their own licenses. Frame Cinema's own code and images
are under the MIT License in `LICENSE`, except the files listed under
[Not under the MIT License](#not-under-the-mit-license).

## Software

| Part | Used for | Terms |
|---|---|---|
| [Godot Engine](https://godotengine.org) 4.7.2 (`app/godot`, the official Linux ARM64 build) | The engine that runs the rooms and menus | MIT, Copyright (c) 2014-present Godot Engine contributors, (c) 2007-2014 Juan Linietsky, Ariel Manzur. Text: `release/licenses/GODOT-LICENSE.txt`. The licenses of the libraries inside the engine: `release/licenses/GODOT-COPYRIGHT.txt` |
| [godot-cpp](https://github.com/godotengine/godot-cpp) | Compiled into the four Godot extensions | MIT, Copyright (c) 2017-present Godot Engine contributors. `release/licenses/GODOT-CPP-LICENSE.md` |
| [OpenVR SDK](https://github.com/ValveSoftware/openvr) header (`app/openvr.h`) | `panel_host` and the menu helper talk to SteamVR | BSD 3-Clause, Copyright (c) 2015, Valve Corporation. `release/licenses/OPENVR-LICENSE.txt` |
| [ncnn](https://github.com/Tencent/ncnn) | Runs the depth model for the 2D-to-3D mode | BSD 3-Clause, Copyright (C) 2017 Tencent. `app/stereo/NCNN-LICENSE.txt` |
| [glslang](https://github.com/KhronosGroup/glslang) 14.0.0 (`app/lib/libglslang.so.14`, `app/lib/libSPIRV.so.14`) | ncnn compiles its 2D-to-3D shaders with it. Copied from SteamOS's package so the app doesn't depend on the system's version | BSD 3-Clause and other permissive terms, listed in `release/licenses/GLSLANG-LICENSE.txt` |
| [SPIRV-Tools](https://github.com/KhronosGroup/SPIRV-Tools) 1.4.309 (`app/lib/libSPIRV-Tools.so`, `app/lib/libSPIRV-Tools-opt.so`) | Used by glslang. Copied from SteamOS's package | Apache License 2.0, The Khronos Group Inc. and contributors. `release/licenses/SPIRV-TOOLS-LICENSE.txt` |
| [ZipDepth](https://github.com/fabiotosi92/ZipDepth) model (`app/stereo/model/`) | Estimates depth for the 2D-to-3D mode | MIT, Copyright (c) 2026 Fabio Tosi. `app/stereo/model/ZIPDEPTH-LICENSE.txt`. It was distilled from Depth Anything V2 Large, whose weights are under CC BY-NC 4.0, so the 3D mode is for non-commercial use only |
| [Inter](https://github.com/rsms/inter) (`app/InterVariable.ttf`) | The interface font | SIL Open Font License 1.1, Copyright (c) 2016 The Inter Project Authors. No Reserved Font Name. `release/licenses/INTER-LICENSE.txt` |

## Rooms

Poly Haven assets use [CC0](https://polyhaven.com/license). Sources are listed
below for attribution and reference.

| Room | What | Source and terms |
|---|---|---|
| Moon | Terrain, rocks and their textures | Poly Haven's [Lunar Landscape](https://polyhaven.com/collections/moon) collection, CC0. Lit and cut down for the headset by Frame Cinema |
| Moon | The Earth in the sky | NASA imagery, public domain (see the Earth row below) |
| Coast | Cliffs, rocks, shoreline, sky | Poly Haven: coastal_cliff_04, coast_land_rocks_02, coast_line_02, coast_rocks_03, rocks_ground_06, qwantani_dusk_2_puresky, all CC0. Water, foam and light made by Frame Cinema |
| Desert | Cliffs, boulders, sand, sky | Poly Haven: namaqualand_cliff_01, namaqualand_cliff_02, namaqualand_boulder_05, sand_02, qwantani_dusk_2_puresky, aerial_beach_01, all CC0 |
| Observation Deck | Cabin, seating, deck, lamps and light | Made for Frame Cinema: modelled by `rooms/observation-deck/build_interior.py` and lit in Blender's Cycles. No outside models, textures or photos |
| Observation Deck, Moon | The Earth: surface, night lights, clouds | NASA, public domain. Blue Marble Next Generation (December 2004), produced by Reto Stöckli, NASA Earth Observatory. Black Marble 2016 (3 km and 500 m), NASA Earth Observatory images by Joshua Stevens, using Suomi NPP VIIRS data from Miguel Román, NASA GSFC. Blue Marble cloud maps (cloud.W and cloud.E), image by Reto Stöckli, render by Robert Simmon, from MODIS data. Resampled by Frame Cinema's scripts. Used under the [NASA Images and Media Usage Guidelines](https://www.nasa.gov/nasa-brand-center/images-and-media/); NASA does not endorse this app |
| Observation Deck | The Milky Way, and the stars fainter than about magnitude 6.5 | See the next section |
| Observation Deck | The brightest stars: position, brightness and colour | The Bright Star Catalogue, 5th Revised Ed. (Preliminary Version), D. Hoffleit and W. H. Warren Jr., Astronomical Data Center, NSSDC/ADC (1991), catalogue V/50 at CDS. Facts from a catalogue; credited with thanks |
| Observation Deck | Nebulae, star clouds and clusters | Made by Frame Cinema's own programs from simulated gas and simulated stars, at the places and sizes published in the Messier, NGC, Barnard and Harris catalogues. Some are drawn larger or brighter than life so they can be seen. The fine grain on the Sagittarius and Scutum star clouds is placed on points of NASA's Deep Star Maps (next section) |
| Observation Deck | A faint scatter of stars away from the Milky Way | Made in the sky's shader. These are invented positions, not real stars |

### The Milky Way and the faint stars

The Milky Way's glow and dust, and the fainter stars, are made from NASA's
[Deep Star Maps 2020](https://svs.gsfc.nasa.gov/4851): NASA/Goddard Space Flight
Center Scientific Visualization Studio. That map is built from ESA's Gaia DR2
survey (Gaia DR2: ESA/Gaia/DPAC) and the Hipparcos and Tycho catalogues (ESA).
NASA's page sets no conditions, but ESA now
[licenses Gaia data](https://www.cosmos.esa.int/web/gaia-users/license) under
[CC BY-NC 3.0 IGO](https://creativecommons.org/licenses/by-nc/3.0/igo/), which
allows free, non-commercial use with credit.

### Not under the MIT License

These files are made from that data. They're under CC BY-NC 3.0 IGO: free for
non-commercial use, with the credit above.

- `app/starship/galaxy.res` and `app/starship/dust.res` (the Milky Way)
- `app/starship/stars.dat` (the star mesh; the faint stars in it sit on the map's bright points)
- `app/starship/objects.dat` (the star grain on two star clouds)
- the pictures that show the Observation Deck's sky: `app/environments/starship-thumb.png`,
  `docs/images/observation-deck.jpg` and the Steam library art `release/art/steam/hero.png`,
  `header.png` and `capsule.png`

Commercial use needs permission from ESA or replacement files. The 2D-to-3D
depth model (`app/stereo/model/`) is also for non-commercial use only; see
ZipDepth above.

## Pictures and branding

- The app icon (`app/branding/frame-cinema-*.png`) is drawn by code,
  `release/art/make-icon-countdown.py`, for Frame Cinema. Its Earth is NASA's
  public-domain imagery (the Earth row above) and its digits are set in Inter.
- The Steam library art (`release/art/steam/`) and the room menu pictures
  (`app/environments/*-thumb.png`) are renders of the app's own rooms. The
  library art's screen shows a render of the Coast room. Other screens show
  Poly Haven's CC0 photo
  [Spruit Sunrise](https://polyhaven.com/a/spruit_sunrise) by Greg Zaal.
- Images in `docs/images/` are app renders.
- No streaming-service logo or artwork is included. The library shows each
  service's name on a coloured tile.

## Not included

Google Chrome and its Widevine video DRM are installed by the user and are under
Google's terms. SteamVR, Gamescope and SteamOS's system libraries are used from
the headset and are not redistributed.

## Trademarks

Netflix, HBO Max, Disney+, Prime Video and Plex are trademarks of their owners.
Their names identify the services opened by the app. Steam and
Steam Frame are trademarks of Valve Corporation. Frame Cinema is an independent
app and is not affiliated with, endorsed by or sponsored by any of them, by NASA
or by ESA.
