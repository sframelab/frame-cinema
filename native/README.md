# Native extensions

This folder contains the source for two Godot extensions:

- `pose-sync/` reads OpenXR timing to align overlays with the room. It does not
  change tracking or submit frames.
- `water-sync/` supplies the current frame's camera for water reflections.

The app loads their libraries from `app/pose-sync/` and `app/water-sync/`.
`tools/fetch_assets.py` retrieves those binaries from a release. Other native
helper sources are under `app/`.

## Build

Both extensions use CMake, [godot-cpp](https://github.com/godotengine/godot-cpp)
at commit `27d9dd23c83871e0619fca5dc2cddfbfd69e926a`, and an API file generated
by the bundled engine. Run on the headset:

```sh
./app/godot --headless --dump-extension-api
cmake -S native/pose-sync -B build/pose-sync -DGODOT_CPP_DIR=<godot-cpp> \
      -DGODOTCPP_CUSTOM_API_FILE=$PWD/extension_api.json -DCMAKE_BUILD_TYPE=Release
cmake --build build/pose-sync
```

Use `native/water-sync` and `build/water-sync` for the water extension.
Each `build-profile.json` limits the build to the Godot classes that extension
uses. See [Native helpers](../docs/build-and-install.md#the-native-helpers)
for the remaining programs.
