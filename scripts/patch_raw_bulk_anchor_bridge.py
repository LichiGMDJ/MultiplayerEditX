from pathlib import Path

path = Path("src/RemoteActionHandler.cpp")
text = path.read_text(encoding="utf-8")

snapshot = "        std::set<GameObject*> snapshotExistingObjects(LevelEditorLayer* editor) {"
if snapshot not in text:
    raise SystemExit("raw bulk anchor bridge: snapshotExistingObjects not found")

# patch_processing_remote_guard.py intentionally inserts ProcessingRemoteGuard
# before snapshotExistingObjects in the first anonymous namespace. Older RAW v3
# expects snapshotExistingObjects to be the first declaration after `namespace {`.
# Split the anonymous namespace at that point. Multiple anonymous namespace
# declarations at the same scope denote the same unnamed namespace in C++, so
# this changes no symbol visibility or runtime behavior.
if "struct ProcessingRemoteGuard" in text:
    before, after = text.split(snapshot, 1)
    marker = "    namespace {\n"

    # Do not apply twice.
    if before.rstrip().endswith("namespace {"):
        print("RAW bulk anchor bridge already present")
    else:
        before = before.rstrip() + "\n    }\n\n    namespace {\n"
        text = before + snapshot + after
        path.write_text(text, encoding="utf-8")
        print("Bridged ProcessingRemoteGuard and RAW bulk-paste anonymous namespace anchors")
else:
    # No RAII guard means the legacy RAW anchor should already be present.
    legacy = "    namespace {\n" + snapshot
    if legacy not in text:
        raise SystemExit("raw bulk anchor bridge: neither ProcessingRemoteGuard nor legacy RAW anchor found")
    print("RAW bulk anchor bridge not needed")

# Strong postcondition used by patch_raw_bulk_paste_v3.py.
final_text = path.read_text(encoding="utf-8")
expected = "    namespace {\n" + snapshot
if expected not in final_text:
    raise SystemExit("raw bulk anchor bridge: expected RAW v3 anchor still missing")
