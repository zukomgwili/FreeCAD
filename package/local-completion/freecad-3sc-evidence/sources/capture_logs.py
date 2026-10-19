"""Mechanically preserve generic source-bug logs; never modify originals."""
import hashlib
import json
from pathlib import Path


SOURCE = Path("/private/tmp/freecad-3sc.I13i45")
DESTINATION = Path(__file__).resolve().parent.parent
LOGS = {
    "old-gui-red1-harness": "native-mixed-gui-red1/run.log",
    "old-gui-red2": "native-mixed-gui-red2/run.log",
    "old-gui-red3": "native-mixed-gui-red3/run.log",
    "old-native-null-red": "null-minimal-red/run.log",
    "final-gui": "native-mixed-gui-final455ff/run.log",
    "final-cold": "native-mixed-cold-final455ff/run.log",
    "build-clean": "full-build-clean.log",
    "ctest-clean-summary": "ctest-clean.log",
    "fem-clean-summary": "fem-clean/run.log",
    "fem-focused-clean": "fem-focused-clean/run.log",
    "materials-app-clean": "materials-app-clean/run.log",
    "materials-gui-clean": "materials-gui-clean/run.log",
    "pipeline-cmd-clean": "pipeline-cmd-clean/run.log",
    "pipeline-gui-clean": "pipeline-gui-clean/run.log",
    "native-focused-clean": "native-focused-clean.log",
    "native-accessor-red": "native-accessor-red.log",
    "native-persistence-quantity-red1-harness-exception": "native-persistence-red.log",
    "native-persistence-quantity-red2-harness-null-loader": "native-persistence-red2.log",
    "native-persistence-quantity-red": "native-persistence-red3.log",
    "native-persistence-mixed-red": "native-persistence-mixed-red.log",
    "native-persistence-shapes-red": "native-persistence-shapes-red.log",
    "native-persistence-inherited-red": "native-persistence-inherited-red.log",
    "native-persistence-inherit-load-red": "native-persistence-inherit-load-red.log",
    "native-persistence-unresolved-red": "native-persistence-unresolved-red.log",
    "native-persistence-atomic-red": "native-persistence-final-atomic-red.log",
    "native-persistence-review-red": "native-persistence-review-red.log",
    "native-final-review-red": "native-final-review-red.log",
    "native-final-review-green": "native-final-review-green.log",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


captures = []
for name, relative in LOGS.items():
    source = SOURCE / relative
    raw = source.read_bytes()
    record = {"source": str(source), "source_bytes": len(raw), "source_sha256": sha(raw)}
    if len(raw) > 128 * 1024:
        if relative == "ctest-clean.log":
            marker = b"\n100% tests passed"
        elif relative == "fem-clean/run.log":
            marker = b"\n----------------------------------------------------------------------\nRan "
        else:
            raise AssertionError(f"No approved large-log summary rule: {relative}")
        offset = raw.rfind(marker)
        assert offset >= 0
        offset += 1
        excerpt = raw[offset:]
        record.update(capture="exact_summary_tail_not_full_log", byte_offset=offset,
                      captured_bytes=len(excerpt), captured_sha256=sha(excerpt),
                      text=excerpt.decode("utf-8"))
    else:
        record.update(capture="complete_lossless_utf8_log", text=raw.decode("utf-8"))
        assert record["text"].encode("utf-8") == raw
    destination = DESTINATION / "logs" / f"{name}.json"
    destination.parent.mkdir(exist_ok=True)
    assert destination.resolve().is_relative_to(DESTINATION)
    encoded = (json.dumps(record, indent=2, ensure_ascii=True) + "\n").encode("utf-8")
    if destination.exists():
        previous = destination.read_bytes()
        if previous != encoded:
            # Explicit evidence-mapping correction: preserve the old exception
            # wrapper under its excluded harness name before replacing this one.
            assert name == "native-persistence-quantity-red"
            old = json.loads(previous)
            assert old["source"] == str(SOURCE / "native-persistence-red.log")
            assert (DESTINATION / "logs/native-persistence-quantity-red1-harness-exception.json").read_bytes() == previous
            with destination.open("wb") as output:
                output.write(encoded)
    else:
        with destination.open("xb") as output:
            output.write(encoded)
    assert source.read_bytes() == raw
    captures.append({"path": str(destination.relative_to(DESTINATION)),
                     "sha256": sha(encoded), "source": str(source),
                     "source_sha256": sha(raw), "capture": record["capture"]})
manifest = {"capture_script_sha256": sha(Path(__file__).read_bytes()), "captures": captures}
with (DESTINATION / "log-captures.json").open("w") as output:
    json.dump(manifest, output, indent=2)
    output.write("\n")
print(json.dumps({"log_captures": len(captures), "all_sources_unchanged": True}))
