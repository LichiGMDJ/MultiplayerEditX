from pathlib import Path

path = Path("src/RemoteActionHandler.cpp")
text = path.read_text(encoding="utf-8")

anchor = '''    namespace {
        std::set<GameObject*> snapshotExistingObjects(LevelEditorLayer* editor) {'''
replacement = '''    namespace {
        struct ProcessingRemoteGuard {
            bool& flag;

            explicit ProcessingRemoteGuard(bool& value) : flag(value) {
                flag = true;
            }

            ProcessingRemoteGuard(ProcessingRemoteGuard const&) = delete;
            ProcessingRemoteGuard& operator=(ProcessingRemoteGuard const&) = delete;

            ~ProcessingRemoteGuard() {
                flag = false;
            }
        };

        std::set<GameObject*> snapshotExistingObjects(LevelEditorLayer* editor) {'''

if anchor not in text:
    raise SystemExit("ProcessingRemoteGuard anchor not found")
text = text.replace(anchor, replacement, 1)

needle = "        m_processingRemote = true;"
count = text.count(needle)
if count == 0:
    raise SystemExit("No m_processingRemote=true assignments found")

text = text.replace(
    needle,
    "        ProcessingRemoteGuard processingRemoteGuard(m_processingRemote);"
)

path.write_text(text, encoding="utf-8")
print(f"Replaced {count} manual remote-processing activations with RAII guards")
