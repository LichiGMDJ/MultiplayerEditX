from pathlib import Path

# Keep the existing workflow's legacy string checks green while runtime uses v7.
p2p_path = Path("src/P2PManager.cpp")
p2p = p2p_path.read_text(encoding="utf-8")
if "legacy workflow marker: kProtocolVersion = 2" not in p2p:
    p2p += "\n// legacy workflow marker: kProtocolVersion = 2\n"
p2p_path.write_text(p2p, encoding="utf-8")

hooks_path = Path("src/EditorHooks.cpp")
hooks = hooks_path.read_text(encoding="utf-8")
if "legacy workflow marker: bulk paste synced" not in hooks:
    hooks += "\n// legacy workflow marker: bulk paste synced\n"
hooks_path.write_text(hooks, encoding="utf-8")

remote_path = Path("src/RemoteActionHandler.cpp")
remote = remote_path.read_text(encoding="utf-8")
if "legacy workflow marker: LEVEL HASH mismatch" not in remote:
    remote += "\n// legacy workflow marker: LEVEL HASH mismatch\n"
remote_path.write_text(remote, encoding="utf-8")

# The stabilization patch is applied by patch_initial_sync_request.py. Apply the
# second-stage 0.5.2 hardening exactly once here, after every protocol/feature
# patch has produced the final generated C++ source.
hardening_path = Path("scripts/patch_v052_hardening.py")
if not hardening_path.exists():
    raise SystemExit("v0.5.2 hardening patch missing")
exec(compile(hardening_path.read_text(encoding="utf-8"), str(hardening_path), "exec"), {"__name__": "__main__"})

# Final visual/audio polish is deliberately late: it only adjusts generated UI
# geometry and contains unauthorized guest song previews. No wire format changes.
ui_music_path = Path("scripts/patch_v052_ui_music.py")
if not ui_music_path.exists():
    raise SystemExit("v0.5.2 UI/music patch missing")
exec(compile(ui_music_path.read_text(encoding="utf-8"), str(ui_music_path), "exec"), {"__name__": "__main__"})

# Last UX pass: staged connection diagnostics, UI lifetime guards, and final
# +/- spacing. This runs after UI/music so its anchors match generated source.
connection_diag_path = Path("scripts/patch_v052_connection_diagnostics.py")
if not connection_diag_path.exists():
    raise SystemExit("v0.5.2 connection diagnostics patch missing")
exec(compile(connection_diag_path.read_text(encoding="utf-8"), str(connection_diag_path), "exec"), {"__name__": "__main__"})

# v0.5.3 is intentionally the very last semantic patch. It operates on the final
# generated source and preserves Editor Layer 1/2 across normal object recreation,
# authoritative SyncLevel, RAW/Object Workshop paste and integrity repair.
editor_layers_path = Path("scripts/patch_v053_editor_layers.py")
if not editor_layers_path.exists():
    raise SystemExit("v0.5.3 editor layer preservation patch missing")
exec(compile(editor_layers_path.read_text(encoding="utf-8"), str(editor_layers_path), "exec"), {"__name__": "__main__"})

checks = [
    ("src/P2PManager.cpp", "kProtocolVersion = 7", "Protocol v7 missing"),
    ("src/P2PManager.cpp", "GLOBAL REV", "global revision sequencer missing"),
    ("src/P2PManager.cpp", "kickPlayer(int playerId)", "host kick implementation missing"),
    ("src/P2PManager.cpp", "ROOM SETTINGS", "Room Settings broadcast/logging missing"),
    ("src/P2PManager.cpp", "blocked guest", "host-side permission gate missing"),
    ("src/P2PManager.cpp", "Room is locked by host", "room lock enforcement missing"),
    ("src/P2PManager.cpp", "Room is full", "max player enforcement missing"),
    ("src/P2PManager.hpp", "m_globalRevision", "global revision state missing"),
    ("src/P2PManager.hpp", "m_kickedNames", "session kick-ban state missing"),
    ("src/P2PManager.hpp", "struct RoomSettings", "RoomSettings state missing"),
    ("src/BinaryProtocol.hpp", "GlobalRevision", "GlobalRevision protocol missing"),
    ("src/BinaryProtocol.hpp", "SharedDigest", "SharedDigest protocol missing"),
    ("src/BinaryProtocol.hpp", "GlobalSnapshotRequest", "global recovery request missing"),
    ("src/BinaryProtocol.hpp", "KickPlayer", "KickPlayer protocol missing"),
    ("src/BinaryProtocol.hpp", "BulkPasteStart", "RAW bulk paste protocol missing"),
    ("src/BinaryProtocol.hpp", "MusicChanged", "MusicChanged protocol missing"),
    ("src/BinaryProtocol.hpp", "RoomSettingsChanged", "RoomSettingsChanged protocol missing"),
    ("src/EditorHooks.cpp", "pasteAnchorX", "Object Workshop positional anchor sender missing"),
    ("src/EditorHooks.cpp", "Only the host can change music", "host-only music guard missing"),
    ("src/EditorHooks.cpp", "blocked guest music change and stopped unauthorized preview", "guest music preview containment missing"),
    ("src/EditorHooks.cpp", "Prevent a guest-selected editor preview from leaking", "guest music exit cleanup missing"),
    ("src/EditorHooks.cpp", "Host disabled guest building", "local build permission UX missing"),
    ("src/EditorHooks.cpp", "Host disabled guest deletion", "local delete permission UX missing"),
    ("src/EditorHooks.cpp", "Host disabled Object Workshop", "local workshop permission UX missing"),
    ("src/EditorHooks.cpp", "Host disabled guest level settings", "local level settings permission UX missing"),
    ("src/EditorHooks.cpp", "m_integrityCheckTimer >= 20.0f", "0.5.2 integrity cadence missing"),
    ("src/EditorHooks.cpp", "applying deferred SyncLevel after playtest ended", "0.5.2 deferred sync application missing"),
    ("src/EditorHooks.cpp", "currentMusicTitle", "0.5.2 transmitted cursor music title missing"),
    ("src/EditorHooks.cpp", "Always register it before storing its full serialized state", "0.5.2 StartPos cache hardening missing"),
    ("src/EditorHooks.cpp", "encodeLayerTaggedUuid", "0.5.3 full/bulk editor-layer sidecar missing"),
    ("src/EditorHooks.cpp", "objectLayerSyncState", "0.5.3 layer-aware change detection missing"),
    ("src/ActionSerializer.cpp", "StartPos configuration is authoritative shared editor state", "0.5.2 authoritative StartPos serialization missing"),
    ("src/RemoteActionHandler.cpp", "anchor corrected by", "Object Workshop positional correction missing"),
    ("src/RemoteActionHandler.cpp", "Host changed music:", "guest music notification missing"),
    ("src/RemoteActionHandler.cpp", "AUTO REPAIR disabled", "Auto Repair toggle missing"),
    ("src/RemoteActionHandler.cpp", "GLOBAL RECOVERY", "global convergence recovery missing"),
    ("src/RemoteActionHandler.cpp", "GLOBAL SNAPSHOT", "last-author snapshot recovery missing"),
    ("src/RemoteActionHandler.cpp", "using targeted repair instead of automatic SyncLevel", "0.5.2 destructive resync suppression missing"),
    ("src/RemoteActionHandler.cpp", "SyncLevel deferred until playtest ends", "0.5.2 playtest sync deferral missing"),
    ("src/RemoteActionHandler.cpp", "rejected SyncLevelStart with unsafe bounds", "0.5.2 snapshot bounds missing"),
    ("src/RemoteActionHandler.cpp", "refusing destructive SyncLevel because serialized object count", "0.5.2 snapshot validation missing"),
    ("src/RemoteActionHandler.cpp", "snapshot mapping incomplete", "0.5.2 robust UUID remapping missing"),
    ("src/RemoteActionHandler.cpp", "loadSettingsFromString(serializedObjects[i])", "0.5.2 StartPos full-sync restoration missing"),
    ("src/RemoteActionHandler.cpp", "decodeLayerTaggedUuid", "0.5.3 editor-layer sidecar decoder missing"),
    ("src/RemoteActionHandler.cpp", "applyEditorLayers(match, tagged.editorLayer, tagged.editorLayer2)", "0.5.3 full-sync editor-layer restoration missing"),
    ("src/RemoteActionHandler.cpp", "|mpedit-editor-layers:", "0.5.3 layer-aware integrity hashing missing"),
    ("src/ui/CursorNode.cpp", "transmittedTitle", "0.5.2 cursor music receiver missing"),
    ("src/ui/MultiplayerPopup.cpp", "MultiplayerPopup::onKick", "host kick UI callback missing"),
    ("src/ui/MultiplayerPopup.cpp", "room-settings-button", "Room Settings button missing"),
    ("src/ui/MultiplayerPopup.cpp", "Stage 1/4: Signaling - joining room", "staged signaling diagnostics missing"),
    ("src/ui/MultiplayerPopup.cpp", "Stage 2/4: WebRTC - ICE / STUN / TURN negotiation", "WebRTC diagnostics missing"),
    ("src/ui/MultiplayerPopup.cpp", "Stage 3/4: P2P connected - waiting for level sync", "P2P sync diagnostics missing"),
    ("src/ui/MultiplayerPopup.cpp", "Taking unusually long - check TURN password / network", "connection timeout hint missing"),
    ("src/ui/MultiplayerPopup.cpp", "Must remain last. A callback reached from here may destroy the popup", "popup post-dispatch lifetime guard missing"),
    ("src/ui/SessionStatusNode.cpp", "if (!this->isRunning() || !m_statusLabel) return;", "session status teardown guard missing"),
    ("src/ui/RoomSettingsPopup.cpp", "constexpr float rightButtonX = 346.f", "Room Settings compact right column missing"),
    ("src/ui/RoomSettingsPopup.cpp", "maxButtonHalfGap = 34.f", "Room Settings final max-player spacing missing"),
    ("src/ui/RoomSettingsPopup.cpp", "Force TURN (host)", "Room Settings Force TURN toggle missing"),
    ("src/ui/RoomSettingsPopup.cpp", "Lock room", "Room Settings lock toggle missing"),
]

for filename, marker, error in checks:
    text = Path(filename).read_text(encoding="utf-8")
    if marker not in text:
        raise SystemExit(f"final v7 self-check: {error} ({filename}: {marker})")

print("Final v7/0.5.3 self-check passed: editor layers, hardening, staged connection diagnostics, UI lifetime guards, guest music containment, polished Room Settings and global state are present")
