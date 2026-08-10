# Multiplayer Edit

<img src="logo.png" width="150" alt="Multiplayer Edit logo" />

Real-time collaborative level editing for Geometry Dash on **Windows x64** and **Android 64-bit**.

This fork uses Protocol v6 with reliable edit delivery, reconnect support, global shared-state recovery, Object Workshop synchronization, host-only music changes, host kick controls, and Room Settings.

## Features

- **Real-Time Collaborative Editing** — host a session, share the 6-character room code, and build together.
- **Windows + Android** — Win64 and Android64 builds use the same multiplayer protocol and can join the same room.
- **Reliable Synchronization** — placement, deletion, movement, transform, settings and bulk operations use reliable delivery and retry logic.
- **Authoritative First Join Sync** — a newly connected player receives the current level before normal collaborative edits begin.
- **Global Shared State** — the room converges to one shared level state even when several players edit.
- **Object Workshop Sync** — RAW paste data and absolute placement are synchronized between players.
- **Host-only Music Changes** — the host controls the global level music and guests receive a notification when it changes.
- **Room Settings** — host controls max players, guest permissions, Auto Repair, room lock, Force TURN diagnostics and kick controls.
- **Reconnect + Recovery** — reconnect handling and integrity recovery help restore the room after temporary connection loss.

## Installation

### Windows

1. Install Geode for Geometry Dash 2.2081.
2. Download the Win64 `.geode` file from this repository's Releases page.
3. Put the `.geode` file into your Geometry Dash `geode/mods/` folder.
4. Restart Geometry Dash.

### Android

1. Install the Android64 version of Geode for Geometry Dash 2.2081.
2. Download the Android64 `.geode` file from the Releases page.
3. Copy the actual `.geode` file into the Android Geode `mods` folder. Do not install the GitHub Actions ZIP itself.
4. Restart Geometry Dash completely.
5. Open Geode's mod list and confirm that **Multiplayer Edit** is enabled.

## Connecting

### Host

1. Open a level in the editor.
2. Open **Multiplayer Edit**.
3. Press **Host**.
4. Share the generated 6-character room code.

### Guest

1. Open **Multiplayer Edit**.
2. Press **Join**.
3. Enter the host's room code.
4. Wait for the initial level synchronization to finish.

The host and guest can be on any supported combination:

- Windows host -> Windows guest
- Windows host -> Android guest
- Android host -> Windows guest
- Android host -> Android guest

Both devices must use compatible Protocol v6 builds.

## Android <-> PC networking

The mod uses WebRTC data channels.

Normal connection mode is **automatic ICE selection**:

1. Direct/local and STUN-discovered routes are preferred.
2. If a direct route is not usable and TURN credentials are configured, TURN is available as a relay candidate.
3. **Force TURN** is intended only for diagnostics and should normally remain disabled.

This means players do not need to enable Force TURN for ordinary sessions.

### If Join stays on `Joining`

First verify that both devices are using the same mod version and that the room code is correct.

Then open the Multiplayer Edit settings and verify:

- **Signaling Server URL** points to the multiplayer signaling server.
- If your network requires a relay, TURN host, username and password are configured.
- **Force TURN Relay** should normally be OFF. Enable it only to test whether a strict NAT/CGNAT is preventing a direct connection.

For diagnostics, check the Geode log for `P2PManager:` lines. Useful milestones are:

- `Joined room ... as player ...`
- `Received host's SDP offer`
- `Reliable channel ... opened`
- `Unreliable channel ... opened`
- `protocol ... verified`
- `requested authoritative initial sync from host`

If signaling succeeds but data channels never open, the problem is normally in ICE/NAT traversal rather than the room-code server.

## Room Settings

The host can open **Room Settings** and control:

- Max players
- Allow guests to build/edit
- Allow guests to delete
- Allow guests to use Object Workshop
- Allow guests to change level settings
- Auto Repair
- Force TURN diagnostic mode
- Kick players
- Lock room

Locking a room prevents new joins but does not remove already connected players.

## Connection Settings

Current builds support a configurable signaling URL and TURN server settings through Geode mod settings.

The signaling server is used only to exchange WebRTC negotiation data. Level editing traffic is sent through WebRTC data channels after the connection is established.

## Build Instructions

This project uses Geode SDK 5.7.1 and targets Geometry Dash 2.2081.

```sh
# Clone
git clone https://github.com/LichiGMDJ/MultiplayerEditX.git
cd MultiplayerEditX

# Windows
geode build --platform win

# Android 64-bit
geode build --platform android64
```

The repository also contains GitHub Actions workflows for Win64 and Android64 builds.

## Release checklist

Before publishing a release, verify at minimum:

- Win64 build succeeds.
- Android64 build succeeds.
- Windows host -> Android guest connects.
- Android host -> Windows guest connects.
- Normal object placement/movement/deletion sync works.
- Object Workshop paste position matches on both devices.
- Room Settings permissions are enforced.
- Host music changes propagate to guests.
- Reconnect and initial level synchronization work.

## Credits

Based on the original Multiplayer Edit project by xXoanon / d050, with additional networking, synchronization, Room Settings and cross-platform work in this fork.
