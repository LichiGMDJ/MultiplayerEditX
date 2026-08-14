#pragma once

#include <string>

namespace mpedit::net {

    struct NetworkConfig {
        std::string signalingUrl;
        std::string turnHost;
        std::string turnUsername;
        std::string turnPassword;
        bool forceTurnRelay = false;

        bool hasSignaling() const { return !signalingUrl.empty(); }
        bool hasTurn() const {
            return !turnHost.empty() && !turnUsername.empty() && !turnPassword.empty();
        }

        static NetworkConfig load();
    };

} // namespace mpedit::net
