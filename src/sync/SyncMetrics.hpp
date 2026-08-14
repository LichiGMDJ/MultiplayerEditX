#pragma once

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <mutex>

namespace mpedit::sync {

    struct SyncMetricsSnapshot {
        double objectsPerSecond = 0.0;
        double bytesPerSecond = 0.0;
        std::size_t reliableQueueDepth = 0;
        uint64_t totalObjectsSerialized = 0;
        uint64_t totalBytesQueued = 0;
    };

    class SyncMetrics final {
    public:
        static SyncMetrics& get();

        void recordSerializedObjects(std::size_t count);
        void recordOutboundBytes(std::size_t bytes);
        void setReliableQueueDepth(std::size_t depth);
        SyncMetricsSnapshot sample();

    private:
        SyncMetrics() = default;

        std::atomic<uint64_t> m_totalObjectsSerialized{0};
        std::atomic<uint64_t> m_totalBytesQueued{0};
        std::atomic<std::size_t> m_reliableQueueDepth{0};

        std::mutex m_sampleMutex;
        uint64_t m_lastObjects = 0;
        uint64_t m_lastBytes = 0;
        uint64_t m_lastSampleMs = 0;
    };

} // namespace mpedit::sync
