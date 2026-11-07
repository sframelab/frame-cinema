# Privacy

Frame Cinema has no accounts, analytics, advertising, payments or automatic
uploads of its own. Chrome, Steam, SteamOS and the streaming services have their
own network activity and privacy policies.

## What the app uses

- **Headset and controller poses** position the room, screen and pointer.
  Controller input operates the menus.
- **Browser profiles** store each service's sign-in, cookies and preferences on
  the headset. You sign in on the service's page in Chrome; Frame Cinema has no
  password form of its own.
- **Playback state** lets the app show controls and send play, pause, seek and
  full-screen commands.
- **Picture samples** provide colors for ambient lighting, black-bar boundaries
  for Fit picture, and depth estimates for the optional 3D mode. Processing
  happens on the headset. Samples used by the lighting and Fit picture features
  are held in memory and temporary local files, which are overwritten during use.

For Plex, the hosted web app connects to your account and media server. Chrome
may ask for local-network access. Frame Cinema does not discover servers,
collect library contents or grant that permission itself.

## How the app talks to Chrome

The app uses local files and pipes to talk to Chrome. It doesn't open a network
port.

For development, the app can save pictures of the service page and the room on
request. That's off unless the app is started with `FRAME_CINEMA_DEVELOPER=1`.

## Files on the headset

| Data | Location |
|---|---|
| Installed app | `~/.local/share/frame-cinema/app` |
| Viewing settings and app logs | `~/.local/share/FrameCinema` |
| Launch log | `~/.local/state/frame-cinema/launch.log` |
| Chrome profiles | `~/.var/app/com.google.Chrome/config/`, in the folders listed below |
| Temporary status, picture samples and control files | `$XDG_RUNTIME_DIR/frame-cinema`, cleared at power off |

Chrome profile folders:

- Netflix: `frame-cinema`
- HBO Max: `frame-cinema-hbomax`
- Disney+: `frame-cinema-disneyplus`
- Prime Video: `frame-cinema-primevideo`
- Plex: `frame-cinema-plex`

## Remove your data

Sign out on each service's page to end its session. To remove the app and its
settings and browser profiles, select **Uninstall Frame Cinema** in the
Desktop Mode application menu. A fresh installation also clears profiles left
by an earlier installation and starts signed out.
