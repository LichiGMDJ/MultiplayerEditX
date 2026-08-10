# 0.5.1
- Added safety guards around WebRTC data-channel sends so oversized editor operations cannot terminate Geometry Dash.
- Large `PlaceObjects` payloads are split into safe reliable-channel batches; oversized single objects are skipped with a warning instead of crashing the game.
- Added inbound packet, incoming queue, and pending-message limits to reduce malformed-packet and runaway-queue risk.
- Added exception containment around network message handlers so malformed remote data cannot escape into the game process.
- Added protocol compatibility handshake (`ProtocolHello`, protocol v1). Editor traffic is ignored until the peer verifies a compatible protocol version.
- Added player music display next to remote cursors. Official songs use their Geometry Dash title; cached custom-song metadata shows `Artist - Song`, with song ID as fallback.
- Switched the custom build to the self-hosted signaling server at `194.226.126.115:8443` and self-hosted TURN/UDP on port 3478.
- TURN credentials are no longer embedded into public build artifacts. The TURN password is read only from local Geode settings.
- Removed normal-log SDP dumps that could expose ICE/network details.
- Added CI checks for the safety guards, protocol handshake, TURN replacement, and music-label patch before compiling the Windows artifact.

# 0.4.4
- Start Position properties are now fully synced between players, except for the enabled/disabled state which is local for each player.
- The multiplayer lobby UI now updates the player count and names in real time as players join or leave.
- Improved playtesting sync to be much smoother and added support for mini and dual.
- Minor changes to about.md and README.md to make some important points easier to understand.
- Fixed a crash that occurred when joining a host caused by a memory issue with teleport portals.
- Fixed a bug where players would sometimes duplicate in the lobby, which caused missing/glitching cursors.
- Fixed a crash that occurred when a guest unexpectedly closes the game.
- Fixed an issue where the game would get stuck on "Waiting for level sync from host..."
- Cleaned up a lot of the codebase.
- Significantly optimized level syncing on massive levels by compressing level data.
- Fixed object ID desyncs for pre-existing level objects when multiple players join.
# 0.4.3
- Fixed a bug where placing, moving, or deleting teleport portals would cause game crashes and duplicate portal desyncs.
- Drastically reduced signaling server load by optimizing polling.

# 0.4.2
- Reduced overlay opacity on objects selected by other players.
- Fixed object desync when quickly deselecting. Objects now sync their final state to all players the moment they are deselected.
- Fixed crash when joining a host.
- Improved cursor accuracy.
- Replaced WebSocket signaling with HTTP long polling.
- Removed "exception based" error handling with error flags, matching Geode guidelines.
- Fixed a bug regarding data channel sends.
- Disabled libdatachannel's WebSocket module to reduce binary size.
- Fixed a race condition where the MessageBatcher would send a stale transform after deselecting, overwriting the correct state.
- Fixed objects not syncing that were tracked but already removed from GD's internal selection array.
- Added a Patreon donate button.

# 0.4.1
- Fixed desync issues with color channels and property edits.
- Fixed multi object rotation being bugged.
- Added a buffer queue to hopefully reduce dropped messages.
- Fixed severe desync and level corruption issues when receiving remote edits while actively playtesting. Edits are now cleanly queued during playtest instead of appearing in realtime. This should hopefully fix certain desync issues.
- Fixed a race condition window when building fast that caused objects to duplicate or drift.
- Replaced HTTP polling-based signaling with a proper WebSocket relay.
- Fixed the signaling server consuming excessive Deno KV reads by removing infinite polling loops. The host no longer polls for new clients, they are pushed instantly via WebSocket.
- Signaling WebSocket is automatically closed once the P2P connection is established, minimizing server resource usage.

# 0.4.0
- Completely overhauled netoworking by switching from a central WebSocket relay server to P2P connections using WebRTC data channels (You may need to reset the URL in the mod settings back to default if you came from an older version).
- Players now connect directly to each other, so there should be no connection bottlenecks in theory.
- Added a lightweight signaling server (Deno Deploy) that only handles initial matchmaking. All game data flows directly between players serverless.
- Replaced JSON message format with a compact binary wire protocol.
- Chunked initial level sync for large levels.
- Removed dependency on the old Render.com relay server (will still stay up for legacy users on older versions).
- Fixed the iOS binary (`.ios.dylib`) missing from the `.geode` package by adding the iOS platform to the automated GitHub Actions build matrix (oops).
- Fixed objects occasionally snapping back to their original position or losing property changes (like color channels) when modifying them rapidly (e.g. copy + paste and then rotate).
- Fixed desyncs when performing extremely fast keyboard inputs before network ticks.

# 0.3.0
- Fixed the synchronizing level screen never loading bug when joining a session.
- Fixed level colors glitching out after joining or when the host changes colors.
- Fixed mirror (flip X/Y) not syncing to other players.
- Fixed flipped objects showing the OPPOSITE flip state on remote players after editing them.
- Fixed host sending a duplicate level sync to itself when a player joins.
- Fixed objects sometimes not appearing after a level sync completes.
- Improved server stability.
- Copy/paste and duplicate now sync as one batched message instead of sending individually, reducing lag.
- Reduced performance overhead in the editor by skipping unnecessary per-frame checks when not actively editing.
- Fixed a rare issue where reconnecting could cause object sync conflicts.
- Internal code cleanup and refactoring.

# 0.2.3
- Increased max payload to 50mb.
- Optimized server loads to prevent dropped connections.

# 0.2.2
- Fixed player icons not showing up when playtesting.
- Fixed random host connection drops/disconnections by forwarding WebSocket `ping` and `pong` to server.
- Added WebSocket ping heartbeats to detect and clean up stale and half-open connections.
- Purged standard C++ exception handling (`try`/`catch`) and exception-prone parser calls (`std::stoi` / `std::stof`), replacing them with Geode's safe `numFromString` utility.

# 0.2.1
- Fixed Use-After-Free crashes (`EXCEPTION_ACCESS_VIOLATION` / DEP violation) during multiplayer editor playtesting and editing by nullifying dangling pointers to deleted objects (like gamemode portals, teleport portals, and rings) on player objects, layer states, and UI fields.
- Fixed a C++ array-out-of-bounds `std::out_of_range` crash when extracting object groups by safely capping group extraction at 10.
- Fixed memory safety on all deletion routes by proactively unregistering deleted objects from the UUID bidirectional maps and tracked selections.

# 0.2.0
- Added proper support for macOS and Android.
- Fixed TLS handshake connection failures on Android and macOS.
- Fixed selector-based scheduler crashes (DEP violations) in the MultiplayerPopup UI.
- Added a 30 second ping interval heartbeat to prevent server idle terminations.
- Deferred the client-side editor exit logic to run on the next frame to prevent use-after-free crashes inside `networkUpdate()`.
- Added a dummy sender node to the `onExitEditor` call to prevent null pointer dereferences inside GD.
- Fixed copy/paste and duplication synchronization in the level editor.
- Fixed initial rendering of text objects for remote players.
- Fixed mobile player cursors drifting when panning the camera.
- Fixed undo/redo synchronization and potential memory corruption crashes by replacing failing `typeinfo_cast` calls in history pruning with type-safe iterations.
- Fixed selection highlights and object locks when copy-pasting or duplicating objects by correcting the host's active session checks in object placement hooks.
- Fixed host level duplication issue when a guest joins.
- Fixed server keeping zombie connections in between hosting levels, causing hosting to break in certain cirumstances.
- Fixed crash when editing triggers.
- Fixed the redo button not bringing back objects when they were deleted.
- Fixed input for server URL to make it possible to actually input URLs manually.

# 0.1.1
- Fixed an EXCEPTION_ACCESS_VIOLATION (DEP violation) crash on Windows/Wine caused by using `schedule_selector` in `$modify` wrapper classes.

# 0.1.0
- Added real-time multiplayer level editing.
- Synchronized object placement, deletion, movement, scaling, rotation, and more.
- Isolated undo/redo stacks per player so actions do not overwrite other players' histories.
- Added live player cursors in the editor.
- Badge previews next to player cursors showing their selected object.
- Live playtesting showing the players custom icons in real-time.
- Added in-editor multiplayer panel (player list, session status HUD overlay, join/leave notifications).
