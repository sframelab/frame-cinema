# Contributing

Frame Cinema is maintained by one person. Focused fixes with a clear explanation
are easiest to review. For a larger change, especially a new room or service,
open an issue before starting.

Read [Build and install](docs/build-and-install.md) first. Changes to rendering,
audio or controls need testing on a Steam Frame.

## Making a change

1. Fetch the assets with `tools/fetch_assets.py`. Before installing a custom
   build, give it a new version in `app/cinema.gd`.
2. Keep the pull request focused and follow the surrounding code style.
3. Run the checks relevant to your change:
   - Installer or packaging: `python3 -m unittest discover -s release -p "test_*.py"` on Linux.
   - Scripts or scenes: the relevant `app/test_*.gd` scripts. For example:
     `./app/godot --headless --path app --xr-mode off --script res://test_picture_fit.gd`.
   - Rooms: check the affected views on the headset, including video playback.
4. After changing a file in `app/starship/`, run
   `python3 rooms/observation-deck/stage_preview.py --refresh-package` to update
   its size and SHA-256 in `package.json`. The build rejects mismatches.
5. Describe the change, its reason and the checks you ran. For headset tests,
   include the app and runtime versions, room, service and observed result.
   Say when a change has only been tested on a PC.

## Project constraints

- **Performance:** measure on the headset, with video playing. A PC preview
  cannot establish VR frame timing. See [Room performance](docs/rooms.md#performance).
- **Browser access:** keep playback commands limited to fixed actions and
  numeric or boolean results, as in `app/media_control.py`. Do not collect
  passwords, cookies or account details.
- **Local communication:** use the private files and pipes already in place.
  Do not add a listening network port.
- **Assets:** keep large textures, meshes and binaries in the release and
  `assets.json`. Put source files and scripts in git.
- **Attribution:** record each asset's source and license in the room's
  `package.json` and [Third-party notices](THIRD_PARTY_NOTICES.md). Do not add
  service logos or artwork from films, games or other projects without permission.

## Reporting a problem

Include the Frame Cinema version shown in the app, your SteamOS and SteamVR
versions, the room and service, the steps to reproduce, and what happened.
The launch log is at `~/.local/state/frame-cinema/launch.log`.

Check logs and screenshots for private information before attaching them.
Never share passwords, tokens, cookies, browser profiles or Steam account folders.
