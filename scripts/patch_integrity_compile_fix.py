from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected source block was not found; refusing to patch")
    return text.replace(old, new, 1)


path = Path("src/ActionSerializer.hpp")
text = path.read_text(encoding="utf-8")

if "#include <unordered_map>" not in text:
    text = text.replace("#include <vector>\n", "#include <vector>\n#include <unordered_map>\n#include <utility>\n", 1)

text = replace_once(
    text,
    '''        std::unordered_map<std::string, std::string> parseSaveString(std::string const& str);\n        std::string buildSaveString(std::unordered_map<std::string, std::string> const& map);\n        void injectLocalStartPosState(ObjectData& remoteData, GameObject* localObj);''',
    '''        std::unordered_map<std::string, std::string> parseSaveString(std::string const& str);\n        std::string buildSaveString(std::unordered_map<std::string, std::string> const& map);\n        std::vector<std::pair<std::string, std::string>> parseSaveStringOrdered(std::string const& str);\n        std::string buildSaveStringOrdered(\n            std::vector<std::pair<std::string, std::string>> const& vec);\n        void injectLocalStartPosState(ObjectData& remoteData, GameObject* localObj);''',
    "ordered save-string helper declarations",
)

path.write_text(text, encoding="utf-8")
print("Exposed ordered save-string helpers required by integrity hashing")
