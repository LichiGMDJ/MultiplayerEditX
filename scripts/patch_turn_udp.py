from pathlib import Path

path = Path("src/P2PManager.cpp")
text = path.read_text(encoding="utf-8")

old = '''        rtc::IceServer turn("openrelay.metered.ca", 443, "openrelayproject", "openrelayproject", rtc::IceServer::RelayType::TurnTcp);\n        config.iceServers.push_back(turn);'''

new = '''        auto turnHost = Mod::get()->getSettingValue<std::string>("turn-host");
        auto turnUsername = Mod::get()->getSettingValue<std::string>("turn-username");
        auto turnPassword = Mod::get()->getSettingValue<std::string>("turn-password");
        auto forceRelay = Mod::get()->getSettingValue<bool>("force-turn-relay");

        if (!turnHost.empty() && !turnUsername.empty() && !turnPassword.empty()) {
            rtc::IceServer turn(
                turnHost,
                3478,
                turnUsername,
                turnPassword,
                rtc::IceServer::RelayType::TurnUdp
            );
            config.iceServers.push_back(turn);

            if (forceRelay) {
                config.iceTransportPolicy = rtc::TransportPolicy::Relay;
            }

            log::info(
                "P2PManager: TURN/UDP configured at {}:3478 (forceRelay={})",
                turnHost,
                forceRelay
            );
        } else {
            log::warn("P2PManager: TURN credentials incomplete; TURN relay disabled");
        }'''

if old not in text:
    raise SystemExit("Expected Metered TurnTcp block was not found; refusing to patch")

text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")
print("Patched src/P2PManager.cpp: Metered TurnTcp -> configurable self-hosted TurnUdp")
