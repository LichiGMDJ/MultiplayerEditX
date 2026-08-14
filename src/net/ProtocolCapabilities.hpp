#pragma once

#include <cstdint>

namespace mpedit::net {

    enum class Capability : uint64_t {
        ReliableAcks       = 1ull << 0,
        EditorLayers       = 1ull << 1,
        RawBulkPaste       = 1ull << 2,
        RoomSettings       = 1ull << 3,
        GlobalRevision     = 1ull << 4,
        TargetedRepair     = 1ull << 5,
        AdaptiveSync       = 1ull << 6,
        HostMigration      = 1ull << 7,
        SecureSignaling    = 1ull << 8,
    };

    constexpr uint32_t kCurrentProtocol = 8;
    constexpr uint32_t kMinimumCompatibleProtocol = 7;

    constexpr uint64_t bit(Capability capability) {
        return static_cast<uint64_t>(capability);
    }

    constexpr uint64_t kLegacyV7Capabilities =
        bit(Capability::ReliableAcks) |
        bit(Capability::EditorLayers) |
        bit(Capability::RawBulkPaste) |
        bit(Capability::RoomSettings) |
        bit(Capability::GlobalRevision) |
        bit(Capability::TargetedRepair);

    constexpr uint64_t kLocalCapabilities =
        kLegacyV7Capabilities |
        bit(Capability::AdaptiveSync) |
        bit(Capability::HostMigration) |
        bit(Capability::SecureSignaling);

    // These are the capabilities required to safely exchange editor state.
    // Optional features are negotiated independently and may be disabled per peer.
    constexpr uint64_t kRequiredCapabilities =
        bit(Capability::ReliableAcks) |
        bit(Capability::EditorLayers);

    constexpr bool hasCapability(uint64_t capabilities, Capability capability) {
        return (capabilities & bit(capability)) != 0;
    }

    constexpr bool hasAll(uint64_t capabilities, uint64_t required) {
        return (capabilities & required) == required;
    }

    constexpr uint64_t normalizeCapabilities(uint32_t protocolVersion, uint64_t advertised) {
        // Protocol v7 predates capability advertisement but its feature set is known.
        if (protocolVersion == 7 && advertised == 0) {
            return kLegacyV7Capabilities;
        }
        return advertised;
    }

    constexpr bool isCompatible(uint32_t protocolVersion, uint64_t advertised) {
        if (protocolVersion < kMinimumCompatibleProtocol) return false;
        return hasAll(normalizeCapabilities(protocolVersion, advertised), kRequiredCapabilities);
    }

} // namespace mpedit::net
