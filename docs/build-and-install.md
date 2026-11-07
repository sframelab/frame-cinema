# Build and install

Edit and preview on a PC, then build and test on the Steam Frame.

## What you need

On the Steam Frame:

- SteamOS for ARM64 with SteamVR.
- Google Chrome, the ARM64 Flatpak, from Discover in Desktop Mode. The app does
  not include Chrome or its video DRM.
- Python 3.11 or later (`python3 --version` in Konsole) and about 6 GB free while
  building: the build folder, the package and the installer are each about 1 GB.

For editing and previews on a PC:

- [Godot 4.7.2](https://godotengine.org/download/archive/4.7.2-stable/) for your system.
- Python 3.11 or later, with `numpy` and `Pillow` for the room tools.
- Blender 4.5 LTS to rebuild the Observation Deck's model and light bake.

## 1. Get the code and assets

```sh
git clone https://github.com/sframelab/frame-cinema.git
cd frame-cinema
```

Room textures, meshes, Godot and prebuilt native helpers come from the release
download. [`assets.json`](../assets.json) records their sizes and SHA-256 hashes.
Fetch them with:

```sh
python3 tools/fetch_assets.py FrameCinema-0.5.19-installer.sh
```

The source can be the installer from the
[Releases page](https://github.com/sframelab/frame-cinema/releases), a locally built `.tar.gz`, or, on a headset that already has this version installed, the installed copy:

```sh
python3 tools/fetch_assets.py ~/.local/share/frame-cinema/app/versions/0.5.19
```

`python3 tools/fetch_assets.py --check` reports missing files or size mismatches.
Add `--verify` to check hashes too. An older release supplies matching assets
and reports the rest as missing.

What comes from the release:

| Files | What they are |
|---|---|
| `app/godot` | The official Godot 4.7.2 Linux ARM64 build (`4.7.2.stable.official.ed1daf0bf`), unchanged. You can also download it from godotengine.org and rename it |
| `app/panel_host`, `app/ambient_sampler`, `app/controller_layer`, `app/native-ui/native_ui_renderer` and the `lib*.so` files | Native programs and Godot extensions built on the headset; see [Native helpers](#the-native-helpers) |
| Everything else under `app/coast`, `app/desert`, `app/lunar`, `app/starship`, `app/ambient-contact`, `app/stereo/model` | Room data: baked light maps, textures, meshes, star data and the 2D-to-3D depth model |

## 2. Set a build version

Reinstalling the same version repairs its files and Steam library entry. Before
building a modified version, raise `"version"` near the top of `app/cinema.gd`, for example from
`0.5.19` to `0.5.19-mine.1`. The menu shows this number.

## 3. Build on the headset

In Desktop Mode, open Konsole in the repository folder and run:

```sh
python3 tools/build_on_frame.py
```

The script verifies assets, runs installer tests and copies `app/` to
`build/<version>/project`. It then imports Godot resources and runs headless
checks with XR off, using a separate data folder for test settings. The output
goes in `dist/<version>/`:

- `FrameCinema-<version>-installer.sh`, the self-extracting installer
- `Install Frame Cinema.desktop`, the double-click launcher for it
- `frame-cinema-<version>-linux-arm64.tar.gz` and `SHA256SUMS`

Logs for each step are in `build/<version>/`.

## 4. Install and run

Either double-click **Install Frame Cinema** in `dist/<version>/`, or run:

```sh
python3 tools/build_on_frame.py --install
```

`--install` refuses while Frame Cinema is open or while the headset is being
worn, because installing restarts Steam. The app goes to
`~/.local/share/frame-cinema/app`, with no administrator password, and keeps the
previous version for rollback. Then return to Gaming Mode and start
**Frame Cinema** from your library, under **Non-Steam**. Running the same
installer again repairs the launcher and the library entry.

Management commands:

```sh
python3 ~/.local/share/frame-cinema/app/manage.py status     # which version is active
python3 ~/.local/share/frame-cinema/app/manage.py rollback   # go back to the previous one
python3 ~/.local/share/frame-cinema/app/manage.py steam      # re-add the Steam library entry
python3 ~/.local/share/frame-cinema/app/manage.py uninstall
```

For startup failures, check `~/.local/state/frame-cinema/launch.log` for missing
requirements or other errors. Panel logs are in `~/.local/share/FrameCinema/logs`.

## Working on a PC

- **Scripts and shaders.** Open `app/` in the Godot 4.7.2 editor. The native
  extensions are built for Linux ARM64 only, so the editor warns that it cannot
  load them; the rooms still open and render.
- **Packaging.** `python tools/build_on_frame.py --skip-tests --skip-godot` makes a
  package on any computer without Godot's import and checks. Use it to check
  packaging; install what you built on the headset.
- **Tests.** The installer tests are in `release/` (`python -m unittest discover -s release -p "test_*.py"`).
  Some use Linux-only calls and fail on Windows. The Godot tests are the
  `app/test_*.gd` scripts, run headless with `--script`.
- **Rooms.** See [rooms.md](rooms.md). The Observation Deck has its own preview
  renderer and an interactive viewer.
- **Developer hooks.** Start the app with `FRAME_CINEMA_DEVELOPER=1` to let your
  own tools ask for pictures of the service page (`browser-capture-request.json`)
  or the room (`observe-request.json`) in `$XDG_RUNTIME_DIR/frame-cinema`. In
  Steam, set the launch options to `FRAME_CINEMA_DEVELOPER=1 %command%`. They're
  off otherwise.

## The native helpers

Each native helper is built by hand on the headset with the commands below,
using `g++`, `cmake` and SteamVR's `libopenvr_api.so` in
`/opt/steamvr/bin/linuxarm64`. The release carries the built copies.

| Program | Source | How it was built |
|---|---|---|
| `panel_host` | `app/panel_host.cpp`, `app/stereo/` | `app/stereo/CMakeLists.txt` (with [ncnn](https://github.com/Tencent/ncnn) for 3D mode). Without 3D mode: `g++ -std=c++17 -O2 -I. panel_host.cpp -L/opt/steamvr/bin/linuxarm64 -lopenvr_api -lX11 -lXtst $(pkg-config --cflags --libs atspi-2 gobject-2.0 cairo) -o panel_host` |
| `ambient_sampler` | `app/ambient_sampler.cpp` | `g++ -std=c++17 -O2 ambient_sampler.cpp -lX11 -lXrender -o ambient_sampler` |
| `native-ui/native_ui_renderer` | `app/native-ui/native_ui_renderer.cpp` | `g++ -std=c++17 -O2 -I. -Inative-ui native-ui/native_ui_renderer.cpp -L/opt/steamvr/bin/linuxarm64 -lopenvr_api -lEGL -lGLESv2 -pthread -Wl,-rpath,/opt/steamvr/bin/linuxarm64 -o native-ui/native_ui_renderer` |
| `native-ui/libframe_native_ui.so` | `app/native-ui/frame_native_ui.cpp` | A Godot extension: `g++ -std=c++17 -O2 -fPIC -shared` against [godot-cpp](https://github.com/godotengine/godot-cpp) at commit `27d9dd23c83871e0619fca5dc2cddfbfd69e926a`, with `-DGDEXTENSION -DLINUX_ENABLED -DTHREADS_ENABLED -DUNIX_ENABLED -DXR_USE_TIMESPEC`, linking `libgodot-cpp.linux.template_release.arm64.a -lopenvr_api -ldl -pthread` |
| `pose-sync/libframe_pose_sync.so`, `water-sync/libframe_water_sync.so` | `native/pose-sync/`, `native/water-sync/` | CMake against the same godot-cpp: `cmake -S native/pose-sync -B build -DGODOT_CPP_DIR=<godot-cpp> -DGODOTCPP_CUSTOM_API_FILE=<extension_api.json> -DCMAKE_BUILD_TYPE=Release` |
| `scene-owner/libframe_scene_owner_broker.so` | `app/scene-owner/frame_scene_owner_broker.cpp` | A Godot extension, built the same way as `libframe_native_ui.so` |
| `controller_layer` | `app/controller_layer_candidate.cpp` | A test program for drawing the controllers in 3D, linked against OpenVR, EGL and GLES 3. It ships, but the app doesn't start it |

`extension_api.json` comes from the engine itself: `./godot --headless --dump-extension-api`.
The OpenVR header (`app/openvr.h`) is Valve's, under the BSD 3-Clause license.
