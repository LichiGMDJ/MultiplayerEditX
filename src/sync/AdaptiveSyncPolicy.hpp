#pragma once

#include <cstddef>

namespace mpedit::sync {

    class AdaptiveSyncPolicy final {
    public:
        static float integrityIntervalSeconds(std::size_t objectCount) {
            if (objectCount <= 5'000) return 20.f;
            if (objectCount <= 20'000) return 45.f;
            if (objectCount <= 50'000) return 180.f;
            return 0.f; // massive levels: integrity is event/repair driven only
        }

        static float externalCompatibilityScanIntervalSeconds(std::size_t objectCount) {
            if (objectCount <= 5'000) return 0.25f;
            if (objectCount <= 20'000) return 1.f;
            if (objectCount <= 50'000) return 3.f;
            return 8.f;
        }

        static bool periodicIntegrityEnabled(std::size_t objectCount) {
            return integrityIntervalSeconds(objectCount) > 0.f;
        }

        static std::size_t fullSnapshotWarningThreshold() {
            return 50'000;
        }
    };

} // namespace mpedit::sync
