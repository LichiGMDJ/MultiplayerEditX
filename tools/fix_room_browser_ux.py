from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing pattern: {label}")
    return text.replace(old, new, 1)

path = Path("src/ui/RoomDiscoveryPopups.cpp")
text = path.read_text(encoding="utf-8")

text = replace_once(
    text,
    '''    this->onClose(nullptr);\n    m_owner->beginHost(roomName, description, playerLimit, m_private, password);''',
    '''    auto* owner = m_owner;\n    this->onClose(nullptr);\n    owner->beginHost(roomName, description, playerLimit, m_private, password);''',
    "create room owner lifetime",
)

text = replace_once(
    text,
    '''    auto password = trimmed(std::string(m_passwordInput->getString()), 48);\n    this->onClose(nullptr);\n    m_owner->beginJoin(m_roomCode, password);''',
    '''    auto password = trimmed(std::string(m_passwordInput->getString()), 48);\n    auto* owner = m_owner;\n    auto roomCode = m_roomCode;\n    this->onClose(nullptr);\n    owner->beginJoin(roomCode, password);''',
    "password popup owner lifetime",
)

text = replace_once(
    text,
    '''    auto password = trimmed(std::string(m_passwordInput->getString()), 48);\n    this->onClose(nullptr);\n    m_owner->beginJoin(code, password);''',
    '''    auto password = trimmed(std::string(m_passwordInput->getString()), 48);\n    auto* owner = m_owner;\n    this->onClose(nullptr);\n    owner->beginJoin(code, password);''',
    "private room owner lifetime",
)

text = replace_once(
    text,
    '''    } else {\n        this->onClose(nullptr);\n        m_owner->beginJoin(room.roomCode, "");\n    }''',
    '''    } else {\n        auto* owner = m_owner;\n        auto code = room.roomCode;\n        this->onClose(nullptr);\n        owner->beginJoin(code, "");\n    }''',
    "public room owner lifetime",
)

if 'this->onClose(nullptr);\n    m_owner->' in text:
    raise RuntimeError("unsafe popup owner access remains")

path.write_text(text, encoding="utf-8")
print("room browser popup lifetime fixes applied")
