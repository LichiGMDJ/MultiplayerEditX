import os
from pathlib import Path

turn_password = os.environ.get("TURN_PASSWORD", "")
if not turn_password:
    raise SystemExit("TURN_PASSWORD environment variable is missing")

turn_password_cpp = turn_password.replace("\\", "\\\\").replace('"', '\\"')

path = Path("src/P2PManager.cpp")
text = path.read_text(encoding="utf-8")

old = '''        rtc::IceServer turn("openrelay.metered.ca", 443, "openrelayproject", "openrelayproject", rtc::IceServer::RelayType::TurnTcp);\n        config.iceServers.push_back(turn);'''

new = f'''        // Self-hosted TURN/UDP credentials are injected only during CI build.
        // The password is not stored in the repository.
        rtc::IceServer turn(
            "194.226.126.115",
            3478,
            "mpedit",
            "{turn_password_cpp}",
            rtc::IceServer::RelayType::TurnUdp
        );
        config.iceServers.push_back(turn);
        config.iceTransportPolicy = rtc::TransportPolicy::Relay;

        log::info(
            "P2PManager: TURN/UDP configured at 194.226.126.115:3478 (forceRelay=true, passwordLen={{}})",
            std::string("{turn_password_cpp}").size()
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
print("Patched P2PManager.cpp for self-hosted signaling and TURN/UDP relay")
