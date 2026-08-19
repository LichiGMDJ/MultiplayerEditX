from pathlib import Path

path = Path("src/RemoteActionHandler.cpp")
text = path.read_text(encoding="utf-8")

start_marker = "            // Match each authoritative serialized record to the recreated object"
end_marker = "            size_t fallbackIndex = uuids.size();"
start = text.find(start_marker)
end = text.find(end_marker, start)
if start < 0 or end < 0:
    raise RuntimeError("snapshot mapping block markers not found")

replacement = '''            // Index recreated objects by authoritative ID + quantized position.
            // The exact path is O(N); nearest-by-ID remains only as a defensive
            // fallback for the rare object whose receiver-side position is normalized.
            auto positionKey = [](int objectID, float x, float y) {
                auto qx = static_cast<long long>(std::llround(static_cast<double>(x) * 1000.0));
                auto qy = static_cast<long long>(std::llround(static_cast<double>(y) * 1000.0));
                return std::to_string(objectID) + ":" + std::to_string(qx) + ":" + std::to_string(qy);
            };

            std::unordered_map<std::string, std::vector<GameObject*>> candidatesByPosition;
            std::unordered_map<int, std::vector<GameObject*>> candidatesById;
            candidatesByPosition.reserve(newObjs.size());
            candidatesById.reserve(newObjs.size());
            for (auto* candidate : newObjs) {
                if (!candidate) continue;
                candidatesByPosition[positionKey(
                    candidate->m_objectID,
                    candidate->getPositionX(),
                    candidate->getPositionY()
                )].push_back(candidate);
                candidatesById[candidate->m_objectID].push_back(candidate);
            }

            std::unordered_set<GameObject*> assigned;
            assigned.reserve(newObjs.size());
            size_t mapped = 0;
            for (size_t i = 0; i < serializedObjects.size(); ++i) {
                int expectedId = serializedObjectId(serializedObjects[i]);
                auto fields = ActionSerializer::parseSaveString(serializedObjects[i]);
                float expectedX = 0.f;
                float expectedY = 0.f;
                if (auto it = fields.find("2"); it != fields.end()) {
                    expectedX = geode::utils::numFromString<float>(it->second).unwrapOr(0.f);
                }
                if (auto it = fields.find("3"); it != fields.end()) {
                    expectedY = geode::utils::numFromString<float>(it->second).unwrapOr(0.f);
                }

                GameObject* match = nullptr;
                auto exactIt = candidatesByPosition.find(positionKey(expectedId, expectedX, expectedY));
                if (exactIt != candidatesByPosition.end()) {
                    auto& exact = exactIt->second;
                    while (!exact.empty() && assigned.contains(exact.back())) {
                        exact.pop_back();
                    }
                    if (!exact.empty()) {
                        match = exact.back();
                        exact.pop_back();
                    }
                }

                if (!match) {
                    auto idIt = candidatesById.find(expectedId);
                    if (idIt != candidatesById.end()) {
                        float bestDistanceSq = 1.0e30f;
                        for (auto* candidate : idIt->second) {
                            if (!candidate || assigned.contains(candidate)) continue;
                            float dx = candidate->getPositionX() - expectedX;
                            float dy = candidate->getPositionY() - expectedY;
                            float distanceSq = dx * dx + dy * dy;
                            if (distanceSq < bestDistanceSq) {
                                bestDistanceSq = distanceSq;
                                match = candidate;
                            }
                        }
                    }
                }

                if (!match) {
                    log::error(
                        "RemoteActionHandler: no recreated object matched snapshot record {} (objectID={}, x={}, y={})",
                        i, expectedId, expectedX, expectedY
                    );
                    continue;
                }

                match->setPosition({expectedX, expectedY});
                assigned.insert(match);
                auto tagged = decodeLayerTaggedUuid(uuids[i]);
                if (tagged.tagged) applyEditorLayers(match, tagged.layer1, tagged.layer2);
                registerObject(tagged.uuid, match);
                ++mapped;

                if (match->m_objectID == 31) {
                    if (auto* startPos = typeinfo_cast<StartPosObject*>(match)) {
                        startPos->loadSettingsFromString(serializedObjects[i]);
                    }
                    updateStartPosCache(match);
                }
            }

'''

text = text[:start] + replacement + text[end:]

required = [
    "candidatesByPosition.reserve(newObjs.size())",
    "candidatesById[candidate->m_objectID].push_back(candidate)",
    "match->setPosition({expectedX, expectedY})",
    "std::llround",
]
for token in required:
    if token not in text:
        raise RuntimeError(f"missing mapping fastpath token: {token}")

path.write_text(text, encoding="utf-8")
print("snapshot mapping fastpath applied")
