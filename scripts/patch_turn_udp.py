import os
from pathlib import Path

turn_password = os.environ.get("TURN_PASSWORD", "")
if not turn_password:
    raise SystemExit("TURN_PASSWORD environment variable is missing")

turn_password_cpp = turn_password.replace("\\", "\\\\").replace('"', '\\"')

path = Path("src/P2PManager.cpp")
text = path.read_text(encoding="utf-8")

old = '''        rtc::IceServer turn("openrelay.metered.ca", 443, "openrelayproject", "openrelayproject", rtc::IceServer::RelayType::TurnTcp);\n        config.iceServers.push_back(turn);'''

new = f'''        auto turnHost = Mod::get()->getSettingValue<std::string>("turn-host");
        auto turnUsername = Mod::get()->getSettingValue<std::string>("turn-username");
        auto turnPassword = Mod::get()->getSettingValue<std::string>("turn-password");
        auto forceTurnRelay = Mod::get()->getSettingValue<bool>("force-turn-relay");

        if (turnHost.empty()) turnHost = "194.226.126.115";
        if (turnUsername.empty()) turnUsername = "mpedit";
        if (turnPassword.empty()) turnPassword = "{turn_password_cpp}";

        rtc::IceServer turn(
            turnHost,
            3478,
            turnUsername,
            turnPassword,
            rtc::IceServer::RelayType::TurnUdp
        );
        config.iceServers.push_back(turn);

        if (forceTurnRelay) {{
            config.iceTransportPolicy = rtc::TransportPolicy::Relay;
        }}

        log::info(
            "P2PManager: TURN/UDP configured at {{}}:3478 (forceRelay={{}}, passwordLen={{}})",
            turnHost,
            forceTurnRelay,
            turnPassword.size()
        );'''

if old not in text:
    raise SystemExit("Expected Metered TurnTcp block was not found; refusing to patch")

text = text.replace(old, new, 1)
text = text.replace(
    'if (url.empty()) return "https://dewy-flea-9364.d050.deno.net";',
    'if (url.empty()) return "https://194.226.126.115:8443";',
    1,
)

path.write_text(text, encoding="utf-8")
print("Patched P2PManager.cpp for self-hosted signaling and configurable TURN/UDP relay")
