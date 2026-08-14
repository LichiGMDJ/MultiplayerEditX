from pathlib import Path

path = Path("src/P2PManager.cpp")
text = path.read_text(encoding="utf-8")

old = '''    rtc::Configuration P2PManager::makeRtcConfig(bool forceRelay) {
        rtc::Configuration config;
        config.iceServers.push_back({"stun:stun.l.google.com:19302"});
        config.iceServers.push_back({"stun:stun.cloudflare.com:3478"});

        auto network = net::NetworkConfig::load();
        if (network.hasTurn()) {
            rtc::IceServer turn(
                network.turnHost, 3478, network.turnUsername, network.turnPassword,
                rtc::IceServer::RelayType::TurnUdp
            );
            config.iceServers.push_back(turn);
            if (network.forceTurnRelay || forceRelay) {
                config.iceTransportPolicy = rtc::TransportPolicy::Relay;
                if (forceRelay && !network.forceTurnRelay) {
                    log::warn("P2PManager: direct/STUN negotiation failed; retrying with TURN relay only");
                } else {
                    log::warn("P2PManager: Force TURN diagnostic mode enabled");
                }
            } else {
                log::info("P2PManager: ICE auto mode: direct/STUN preferred, TURN fallback available");
            }
        } else {
            log::info("P2PManager: ICE direct/STUN mode; TURN is not configured");
        }
        return config;
    }
'''

new = '''    rtc::Configuration P2PManager::makeRtcConfig(bool forceRelay) {
        rtc::Configuration config;

        // Prefer direct peer-to-peer connectivity. STUN exposes server-reflexive
        // candidates and remains the cheapest/lowest-latency path when NAT allows it.
        config.iceServers.push_back({"stun:stun.l.google.com:19302"});
        config.iceServers.push_back({"stun:stun.cloudflare.com:3478"});

        auto network = net::NetworkConfig::load();
        bool customTurnAvailable = network.hasTurn();

        // User/self-hosted relay is preferred when configured.
        if (customTurnAvailable) {
            rtc::IceServer customTurn(
                network.turnHost, 3478, network.turnUsername, network.turnPassword,
                rtc::IceServer::RelayType::TurnUdp
            );
            config.iceServers.push_back(customTurn);
        }

        // 0.5.2 always exposed this TURN/TCP relay to ICE. Restoring it as a
        // compatibility fallback reproduces the old zero-configuration behavior:
        // direct/STUN candidates are still preferred, but restrictive NAT/CGNAT or
        // blocked UDP can transparently fall back to TURN over TCP/443.
        rtc::IceServer compatibilityTurn(
            "openrelay.metered.ca", 443,
            "openrelayproject", "openrelayproject",
            rtc::IceServer::RelayType::TurnTcp
        );
        config.iceServers.push_back(compatibilityTurn);

        if (network.forceTurnRelay || forceRelay) {
            config.iceTransportPolicy = rtc::TransportPolicy::Relay;
            if (forceRelay && !network.forceTurnRelay) {
                log::warn("P2PManager: direct/STUN negotiation failed; retrying with relay-only ICE");
            } else {
                log::warn("P2PManager: Force TURN diagnostic mode enabled");
            }
        } else if (customTurnAvailable) {
            log::info(
                "P2PManager: ICE auto mode: direct/STUN preferred, custom TURN/UDP + compatibility TURN/TCP fallback available"
            );
        } else {
            log::info(
                "P2PManager: ICE auto mode: direct/STUN preferred, compatibility TURN/TCP fallback available"
            );
        }

        return config;
    }
'''

if old not in text:
    raise SystemExit("makeRtcConfig block no longer matches expected source")

path.write_text(text.replace(old, new, 1), encoding="utf-8")
