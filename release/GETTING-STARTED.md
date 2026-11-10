# Getting started

Frame Cinema plays Netflix, HBO Max, Disney+, Prime Video and Plex in a VR
cinema on Steam Frame. Choose the Moon, Coast, Desert, Observation Deck or
Dark Room. The app and browser run on the headset; Plex libraries also need
a reachable Plex Media Server.

You'll need your own service accounts and any required subscriptions.
Availability and picture quality depend on the provider, subscription, region
and browser support. Frame Cinema is an independent app.

## Requirements

- Steam Frame running SteamOS ARM64 with SteamVR.
- **Google Chrome ARM64 Flatpak**, installed for your user or system-wide.
  In Desktop Mode, find Google Chrome in Discover. Chrome and its video DRM
  are not included with Frame Cinema.
- About 3 GB of free storage during installation.

## Install

1. In Desktop Mode, download `FrameCinema-0.5.20-installer.sh` and
   `Install Frame Cinema.desktop` into the same folder.
2. Double-click **Install Frame Cinema** and choose **Continue**. A terminal
   shows progress while the installer checks requirements, prepares resources
   and adds the Steam library entry. This takes a few minutes. Steam restarts
   at the end.
3. Return to Gaming Mode and launch **Frame Cinema**. It is under **Non-Steam**
   in your library, not with your Steam games.

You can also install from a terminal with
`sh FrameCinema-0.5.20-installer.sh`. The app installs in
`~/.local/share/frame-cinema/app` without an administrator password.
Updates keep your settings, sign-ins and the previous version.

## Watch

1. Launch Frame Cinema. Steam's menu closes by itself once the room is ready.
2. Sit comfortably, look forward and select **Recenter**.
3. Choose a service and sign in. Each service remembers its own sign-in.
4. Point and press a trigger to select. Use the thumbstick to scroll.

Open **Environment** to change the room, screen size and lighting. **Focus**
hides the controls and dims the room. Press **B** or a trigger to bring the
controls back. Controllers fade while idle and return when moved.

Select a text field, then use **Keyboard** or grip to type. A key types when
you let go of the trigger, even if your aim has slipped onto the next key. Move
off the keyboard before letting go to cancel. Captions, audio languages and
profiles are in the service's player controls.

### Fit picture

**Fit picture**, in Environment, hides black bars in Focus after they have
been steady for about a second. Using the controllers restores the full picture
so you can reach the player's controls.

Brief overlays and dark scenes leave the crop in place. Persistent captions or
picture content in the bars restore the full picture until the next title.
Turn Fit picture off if it crops anything you want to see.

### Observation Deck

Look up for the brightest part of the Milky Way. The sky around the screen is
dimmer, and Focus dims the Earth and sky further. Carina and the Magellanic
Clouds are included but are outside the view from the seat.

The brighter stars and catalogued objects are at their real positions. A faint
background layer uses invented positions.

### Prime Video and Plex

Prime Video opens the service's website. Sign in with your Amazon account and
choose a title. Picture quality is subject to Amazon's Linux browser support.

Plex opens the hosted Plex Web app. Sign in with an account that can access your
server, and keep that server running and reachable. If Chrome asks for
local-network access, allow it to connect to a local server. Playback formats,
transcoding and subscription requirements depend on Chrome and your Plex setup.

If Frame Cinema's play or seek buttons are unavailable, use the service's player.

## Troubleshooting

| Problem | Try |
|---|---|
| The app does not start | Read `~/.local/state/frame-cinema/launch.log` for missing requirements, such as Chrome |
| Steam's menu stays over the room | Press the Steam button once |
| The screen is off to one side | Look forward and select **Recenter** |
| Controls are hidden | Press **B** or a trigger |
| A page stops responding | **More → Reload service**, then **Reopen service** if needed |
| Picture quality is lower than expected | Check the service's quality settings and subscription; 4K and HDR are not guaranteed |
| Sign-in has expired | Sign in again on the service's page |
| Motion feels uneven | Try Dark Room, Desert or Lunar Landscape |

**Reopen service** preserves your sign-in. Close Frame Cinema through Steam's
normal close-game action. Take a break if viewing is uncomfortable.

## Update, roll back or uninstall

- **Update:** run the newer installer. It keeps your settings and sign-ins.
- **Roll back:** in Konsole, run
  `python3 ~/.local/share/frame-cinema/app/manage.py rollback`.
- **Missing from your Steam library?** Look under **Non-Steam** first. If it
  isn't there, run the installer again: it repairs the entry. You can also run
  `python3 ~/.local/share/frame-cinema/app/manage.py steam`.
- **Uninstall:** select **Uninstall Frame Cinema** in the Desktop Mode
  application menu. After confirmation, it removes the app, Steam entry,
  settings and all service sign-ins stored by Frame Cinema, then restarts Steam.
  A fresh installation starts signed out.

When reporting a problem, include the app version, room, service, steps and
observed result. Check logs and screenshots for private information before
sharing them. Do not share passwords, cookies or browser-profile folders.

See [Privacy](PRIVACY.md) for local data storage and
[Third-party notices](THIRD-PARTY-NOTICES.md) for credits and asset terms.
