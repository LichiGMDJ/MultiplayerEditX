from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected source block was not found; refusing to patch")
    return text.replace(old, new, 1)

p2p_path = Path("src/P2PManager.cpp")
p2p = p2p_path.read_text(encoding="utf-8")

old = '''        if (!turnPassword.empty()) {
            rtc::IceServer turn(
                turnHost,
                3478,
                turnUsername,
                turnPassword,
                rtc::IceServer::RelayType::TurnUdp
            );
            config.iceServers.push_back(turn);

            if (forceTurnRelay) {
                config.iceTransportPolicy = rtc::TransportPolicy::Relay;
            }

            log::info(
                "P2PManager: TURN/UDP configured at {}:3478 (forceRelay={})",
                turnHost,
                forceTurnRelay
            );
        } else {
            log::warn("P2PManager: TURN password is empty; TURN relay disabled for this client");
        }'''

new = '''        // Normal mode is ICE automatic selection: host/srflx (direct/STUN)
        // candidates are preferred by ICE and TURN remains available as a
        // relay candidate only when a direct route cannot be established.
        // Force TURN is intentionally diagnostic-only.
        if (!turnPassword.empty()) {
            rtc::IceServer turn(
                turnHost,
                3478,
                turnUsername,
                turnPassword,
                rtc::IceServer::RelayType::TurnUdp
            );
            config.iceServers.push_back(turn);

            if (forceTurnRelay) {
                config.iceTransportPolicy = rtc::TransportPolicy::Relay;
                log::warn("P2PManager: Force TURN diagnostic mode enabled");
            } else {
                log::info("P2PManager: ICE auto mode: direct/STUN preferred, TURN fallback available");
            }
        } else {
            log::info("P2PManager: ICE direct/STUN mode; no TURN credentials configured");
        }'''

p2p = replace_once(p2p, old, new, "automatic ICE fallback configuration")
p2p_path.write_text(p2p, encoding="utf-8")
print("Configured ICE auto mode: direct/STUN preferred with TURN fallback")
