#include "NetworkConfig.hpp"

#include <Geode/loader/Mod.hpp>
#include <algorithm>
#include <cctype>

using namespace geode::prelude;

namespace mpedit::net {

    ConnectionMode NetworkConfig::parseConnectionMode(std::string value) {
        std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
            return static_cast<char>(std::tolower(c));
        });
        if (value == "webrtc") return ConnectionMode::WebRTC;
        if (value == "turn") return ConnectionMode::Turn;
        if (value == "http relay" || value == "http-relay" || value == "http_relay") {
            return ConnectionMode::HttpRelay;
        }
        return ConnectionMode::Auto;
    }

    std::string NetworkConfig::transportModeName() const {
        switch (connectionMode) {
            case ConnectionMode::WebRTC: return "webrtc";
            case ConnectionMode::Turn: return "turn";
            case ConnectionMode::HttpRelay: return "http-relay";
            case ConnectionMode::Auto:
            default: return "auto";
        }
    }

    NetworkConfig NetworkConfig::load() {
        auto* mod = Mod::get();

        NetworkConfig config;
        config.signalingUrl = mod->getSettingValue<std::string>("signaling-url");
        while (config.signalingUrl.size() > 1 && config.signalingUrl.back() == '/') {
            config.signalingUrl.pop_back();
        }
        config.turnHost = mod->getSettingValue<std::string>("turn-host");
        config.turnUsername = mod->getSettingValue<std::string>("turn-username");
        config.turnPassword = mod->getSettingValue<std::string>("turn-password");
        config.forceTurnRelay = mod->getSettingValue<bool>("force-turn-relay");
        config.connectionMode = parseConnectionMode(
            mod->getSettingValue<std::string>("connection-mode")
        );
        return config;
    }

} // namespace mpedit::net
