from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing pattern: {label}")
    return text.replace(old, new, 1)

# Make ctype usage explicit and close the browser before password entry.
path = Path("src/ui/RoomDiscoveryPopups.cpp")
text = path.read_text(encoding="utf-8")
if "#include <cctype>" not in text:
    text = replace_once(text, "#include <algorithm>\n", "#include <algorithm>\n#include <cctype>\n", "cctype include")
text = replace_once(
    text,
    '''    if (room.hasPassword) {
        PasswordPopup::create(m_owner, room.roomCode, room.roomName)->show();
    } else {''',
    '''    if (room.hasPassword) {
        auto* owner = m_owner;
        auto code = room.roomCode;
        auto name = room.roomName;
        this->onClose(nullptr);
        if (auto* popup = PasswordPopup::create(owner, std::move(code), std::move(name))) {
            popup->show();
        }
    } else {''',
    "close browser before password popup",
)
path.write_text(text, encoding="utf-8")

# Surface password errors as user-facing room errors rather than raw HTTP 403.
path = Path("src/P2PManager.cpp")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''                } else if (res.code() == 404) {
                    if (m_state.load() == State::Reconnecting) {''',
    '''                } else if (res.code() == 403) {
                    if (m_state.load() == State::Reconnecting) {
                        log::warn("P2PManager: reconnect join rejected with 403; stopping reconnect");
                    }
                    std::vector<ErrorCb> callbacks;
                    std::string err;
                    {
                        std::lock_guard lock(m_stateMutex);
                        m_error = "Invalid room password";
                        m_state.store(State::Error);
                        callbacks = m_onError;
                        err = m_error;
                    }
                    for (auto& cb : callbacks) cb(err);
                } else if (res.code() == 404) {
                    if (m_state.load() == State::Reconnecting) {''',
    "join 403 password error",
)
path.write_text(text, encoding="utf-8")

print("room browser UX fixes applied")
