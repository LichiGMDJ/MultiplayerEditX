from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"v0.5.2 UI/music: {label}: expected source block not found")
    return text.replace(old, new, 1)


# -----------------------------------------------------------------------------
# Room Settings visual polish.
# Keep both columns comfortably inside the popup and add real spacing between
# the Max Players +/- buttons so their green sprites never visually merge.
# -----------------------------------------------------------------------------
room_path = Path("src/ui/RoomSettingsPopup.cpp")
room = room_path.read_text(encoding="utf-8")

room = replace_once(
    room,
    '''    constexpr float leftLabelX = 34.f;
    constexpr float leftButtonX = 176.f;
    constexpr float rightLabelX = 220.f;
    constexpr float rightButtonX = 364.f;
    constexpr float toggleWidth = 62.f;''',
    '''    constexpr float leftLabelX = 34.f;
    constexpr float leftButtonX = 166.f;
    constexpr float rightLabelX = 238.f;
    constexpr float rightButtonX = 346.f;
    constexpr float toggleWidth = 58.f;''',
    "Room Settings column geometry",
)

room = replace_once(
    room,
    '''    auto* minus = makeButton("-", this, menu_selector(RoomSettingsPopup::onMaxMinus), 34.f);
    minus->setPosition({center.width + 18.f, topY});
    menu->addChild(minus);

    auto* plus = makeButton("+", this, menu_selector(RoomSettingsPopup::onMaxPlus), 34.f);
    plus->setPosition({center.width + 58.f, topY});''',
    '''    auto* minus = makeButton("-", this, menu_selector(RoomSettingsPopup::onMaxMinus), 30.f);
    minus->setPosition({center.width + 20.f, topY});
    menu->addChild(minus);

    auto* plus = makeButton("+", this, menu_selector(RoomSettingsPopup::onMaxPlus), 30.f);
    plus->setPosition({center.width + 62.f, topY});''',
    "Max Players button spacing",
)

room = replace_once(
    room,
    '''        name->setScale(0.40f);''',
    '''        name->setScale(0.38f);''',
    "Room Settings label scale",
)

room = replace_once(
    room,
    '''    note->setPosition({rightButtonX - 34.f, row4});''',
    '''    note->setPosition({rightButtonX - 18.f, row4});''',
    "Force TURN note alignment",
)

room_path.write_text(room, encoding="utf-8")


# -----------------------------------------------------------------------------
# Guest music authority / preview leakage.
# levelSettingsUpdated() runs after GD has already reacted to the song picker,
# so restoring only songID/audioTrack is not enough: a preview may already be
# playing. Stop it immediately for rejected guest changes, then restore host
# metadata. Also stop any leaked preview when a guest exits the multiplayer
# editor so it cannot continue into EditLevelLayer / menus.
# -----------------------------------------------------------------------------
hooks_path = Path("src/EditorHooks.cpp")
hooks = hooks_path.read_text(encoding="utf-8")

old_guest_music = '''            } else if (session.getRole() == SessionManager::Role::Client &&
                       (currentSong != m_fields->m_lastHostSongID || currentTrack != m_fields->m_lastHostAudioTrack)) {
                this->m_level->m_songID = m_fields->m_lastHostSongID;
                this->m_level->m_audioTrack = m_fields->m_lastHostAudioTrack;
                Notification::create("Only the host can change music", NotificationIcon::Warning)->show();
                return;'''
new_guest_music = '''            } else if (session.getRole() == SessionManager::Role::Client &&
                       (currentSong != m_fields->m_lastHostSongID || currentTrack != m_fields->m_lastHostAudioTrack)) {
                // GD may start the newly selected song preview before this
                // callback fires. Stop that unauthorized preview first, then
                // restore the authoritative host metadata.
                if (auto* audio = FMODAudioEngine::sharedEngine()) {
                    audio->stopAllMusic(true);
                }
                this->m_level->m_songID = m_fields->m_lastHostSongID;
                this->m_level->m_audioTrack = m_fields->m_lastHostAudioTrack;
                Notification::create("Only the host can change music", NotificationIcon::Warning)->show();
                log::info("EditorHooks: blocked guest music change and stopped unauthorized preview");
                return;'''
hooks = replace_once(hooks, old_guest_music, new_guest_music, "guest music preview stop")

old_exit = '''    void onExit() {
        LevelEditorLayer::onExit();
        
        auto& session = SessionManager::get();
        if (session.isInSession()) {
            session.leaveSession();'''
new_exit = '''    void onExit() {
        LevelEditorLayer::onExit();
        
        auto& session = SessionManager::get();
        if (session.isInSession()) {
            if (session.getRole() == SessionManager::Role::Client) {
                // Prevent a guest-selected editor preview from leaking into the
                // normal Geometry Dash level/menu screens after leaving MP.
                if (auto* audio = FMODAudioEngine::sharedEngine()) {
                    audio->stopAllMusic(true);
                }
            }
            session.leaveSession();'''
hooks = replace_once(hooks, old_exit, new_exit, "guest music cleanup on editor exit")

hooks_path.write_text(hooks, encoding="utf-8")


checks = [
    (room_path, "constexpr float rightButtonX = 346.f"),
    (room_path, "center.width + 62.f"),
    (hooks_path, "blocked guest music change and stopped unauthorized preview"),
    (hooks_path, "Prevent a guest-selected editor preview from leaking"),
    (hooks_path, "audio->stopAllMusic(true)"),
]
for path, marker in checks:
    if marker not in path.read_text(encoding="utf-8"):
        raise SystemExit(f"v0.5.2 UI/music self-check failed: {path}: {marker}")

print("Patched v0.5.2 UI/music: Room Settings alignment + guest preview containment")
