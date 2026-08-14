#pragma once

#include <string>

namespace mpedit::net {

    enum class ConnectionMode {
        Auto,
        WebRTC,
        Turn,
        HttpRelay,
    };

    struct NetworkConfig {
        std::string signalingUrl;
        std::string turnHost;
        std::string turnUsername;
        std::string turnPassword;
        bool forceTurnRelay = false;
        ConnectionMode connectionMode = ConnectionMode::Auto;

        bool hasSignaling() const { return !signalingUrl.empty(); }
        bool hasTurn() const {
            return !turnHost.empty() && !turnUsername.empty() && !turnPassword.empty();
        }

        bool httpRelayImmediate() const { return connectionMode == ConnectionMode::HttpRelay; }
        bool allowsHttpRelayFallback() const {
            return connectionMode == ConnectionMode::Auto || connectionMode == ConnectionMode::HttpRelay;
        }
        bool forceTurnTransport() const {
            return forceTurnRelay || connectionMode == ConnectionMode::Turn;
        }
        bool directWebRtcOnly() const { return connectionMode == ConnectionMode::WebRTC; }
        std::string transportModeName() const;

        static ConnectionMode parseConnectionMode(std::string value);
        static NetworkConfig load();
    };

} // namespace mpedit::net
