#include "NetworkConfig.hpp"

#include <Geode/loader/Mod.hpp>

using namespace geode::prelude;

namespace mpedit::net {

    NetworkConfig NetworkConfig::load() {
        auto* mod = Mod::get();

        NetworkConfig config;
        config.signalingUrl = mod->getSettingValue<std::string>("signaling-url");
        config.turnHost = mod->getSettingValue<std::string>("turn-host");
        config.turnUsername = mod->getSettingValue<std::string>("turn-username");
        config.turnPassword = mod->getSettingValue<std::string>("turn-password");
        config.forceTurnRelay = mod->getSettingValue<bool>("force-turn-relay");
        return config;
    }

} // namespace mpedit::net
