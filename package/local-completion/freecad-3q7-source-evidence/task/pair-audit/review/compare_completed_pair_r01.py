"""Independent stdlib-only reads of completed private benchmark pair outputs.

No product imports, process spawning, native execution, live build/source reads,
or input writes. Results are printed for the reviewer to preserve separately.
"""

import hashlib
import json
from pathlib import Path
import re


TASK = Path("/private/tmp/freecad-3q7-Pq3Byy")
LEGS = ("large-baseline-r02", "large-candidate-r02")
EXPECTED_EXECUTION = (
    "fd97c389e80593076fe035573fb357ae4836bd955aca7aad72541cae9fd14a36",
    "df10f37e56e1ff2c91d5bb735c5b60e48bbb876e6911e4a72c1a1b9f6c887da6",
)
READS = {}


def require(condition, description):
    if not condition:
        raise AssertionError(description)


def descriptor(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def read(relative):
    path = TASK / relative
    require(path.is_file() and not path.is_symlink(), f"Missing or symlink input: {path}")
    raw = path.read_bytes()
    observed = descriptor(raw)
    require(READS.setdefault(str(path), observed) == observed, f"Input changed: {path}")
    return raw


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def parse(raw):
    return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda value: (_ for _ in ()).throw(
        AssertionError(f"Nonfinite JSON constant: {value}")))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def group_map(groups):
    require(type(groups) is list, "Groups are not a list")
    by_key, by_id = {}, {}
    for group in groups:
        require(type(group) is dict and set(group) == {"id", "name", "element_type", "elements"},
                "Unexpected group record fields")
        require(type(group["id"]) is int and group["id"] > 0 and type(group["name"]) is str
                and type(group["element_type"]) is str and type(group["elements"]) is list
                and all(type(value) is int and value > 0 for value in group["elements"]),
                "Invalid group record type")
        key = (group["name"], group["element_type"])
        require(key not in by_key and group["id"] not in by_id, "Duplicate group key or numeric handle")
        by_key[key] = {name: value for name, value in group.items() if name != "id"}
        by_id[group["id"]] = key
    return by_key, by_id


def main():
    amendment = parse(read("proposals/benchmark-native-group-handle-amendment-r01.json"))
    require(amendment["passed"] is True, "Comparison amendment is not approved")
    profiles, executions, snapshots, within = {}, {}, {}, {}
    for leg, expected_execution in zip(LEGS, EXPECTED_EXECUTION):
        raw_execution = read(leg + "/execution.json")
        require(descriptor(raw_execution)["sha256"] == expected_execution,
                "Completed execution receipt is not the assigned receipt")
        executions[leg] = parse(raw_execution)
        require(executions[leg]["passed"] is True, "Assigned completed leg is not passed")
        profiles[leg] = parse(read(leg + "/export-profile.json"))
        before, after = (read(leg + "/mesh-" + phase + ".json") for phase in ("before", "after"))
        require(before == after, "Full raw snapshot changed within leg: " + leg)
        snapshots[leg] = parse(before)
        within[leg] = {"full_raw_before_after_bytes_identical": True,
                       "before": descriptor(before), "after": descriptor(after)}

    baseline, candidate = (snapshots[leg] for leg in LEGS)
    expected_components = {"all_element_connectivity", "groups", "nodes", "ordered_all_element_ids",
                           "ordered_analysis_group", "raw_mesh_provenance", "volume_connectivity"}
    require(set(baseline) == set(candidate) == expected_components, "Wrong raw snapshot components")
    component_checks, component_descriptors = {}, {}
    for name in sorted(expected_components - {"groups"}):
        one, two = canonical(baseline[name]), canonical(candidate[name])
        require(one == two, "Non-group component differs: " + name)
        component_checks[name] = True
        component_descriptors[name] = descriptor(one)

    baseline_groups, baseline_ids = group_map(baseline["groups"])
    candidate_groups, candidate_ids = group_map(candidate["groups"])
    require(len(baseline_groups) == len(candidate_groups) == 9531, "Wrong unique group count")
    require([group["id"] for group in baseline["groups"]] == [group["id"] for group in candidate["groups"]],
            "Ordered native numeric group-handle lists differ")
    require(set(baseline_groups) == set(candidate_groups), "Named/type group key sets differ")
    require(all(canonical(baseline_groups[key]) == canonical(candidate_groups[key]) for key in baseline_groups),
            "Named/type group exact ordered element membership differs")
    handle_reassignments = sum(baseline_ids[number] != candidate_ids[number] for number in baseline_ids)
    require(handle_reassignments > 0, "Expected recorded restore-local group-handle assignment difference missing")
    named = sorted(baseline_groups.values(), key=lambda group: (group["name"], group["element_type"]))
    named_group_descriptor = descriptor(canonical(named))
    comparable = dict(baseline)
    comparable["groups"] = named
    comparable["ordered_native_group_handles"] = [group["id"] for group in baseline["groups"]]
    comparable_descriptor = descriptor(canonical(comparable))
    require(all(profiles[leg]["comparable_mesh_before_sha256"]
                == profiles[leg]["comparable_mesh_after_sha256"]
                == comparable_descriptor["sha256"] for leg in LEGS),
            "Recorded named-group-comparable snapshot hash differs")

    recorded_pins = [executions[leg]["compiled_native_pins"] for leg in LEGS]
    require(all(type(value) is dict and len(value) == 63 for value in recorded_pins), "Wrong recorded native pin maps")
    require(canonical(recorded_pins[0]) == canonical(recorded_pins[1]), "Recorded 63 native pins differ")

    requests = [read(leg + "/native/Mesh.accounting") for leg in LEGS]
    require(requests[0] == requests[1], "Original accounting request bytes differ across the completed pair")
    decks = [read(leg + "/native/Mesh.inp") for leg in LEGS]
    lines = [deck.splitlines(keepends=True) for deck in decks]
    require(len(lines[0]) == len(lines[1]), "Deck line counts differ")
    prefix = b"**   written on    --> "
    comments = [[(index, line) for index, line in enumerate(values) if line.startswith(prefix)] for values in lines]
    require(all(len(value) == 1 for value in comments), "Not exactly one timestamp comment in each deck")
    timestamp_index = comments[0][0][0]
    require(comments[1][0][0] == timestamp_index, "Timestamp-comment line positions differ")
    timestamp_pattern = re.compile(
        rb"\*\*   written on    --> (?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) "
        rb"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) [ 0-3]\d [0-2]\d:[0-5]\d:[0-5]\d \d{4}\n")
    require(all(timestamp_pattern.fullmatch(value[0][1]) for value in comments), "Unexpected timestamp-comment bytes")
    changed_lines = [index for index, (one, two) in enumerate(zip(*lines)) if one != two]
    require(changed_lines == [timestamp_index], "Deck differs outside the one exact timestamp comment")
    for leg, values in zip(LEGS, comments):
        require([values[0][1].decode("ascii").rstrip("\n")] == profiles[leg]["declared_written_on_comments"]["new"],
                "Recorded timestamp-comment literal differs")
    normalized_deck = b"".join(lines[0][:timestamp_index] + [prefix + b"<TIMESTAMP>\n"] + lines[0][timestamp_index + 1:])

    producer_raw_components = {}
    for leg in LEGS:
        component_sha = {name: hashlib.sha256(canonical(value)).hexdigest() for name, value in snapshots[leg].items()}
        profile = profiles[leg]
        require(component_sha == profile["mesh_before_component_sha256"] == profile["mesh_after_component_sha256"],
                "Recorded raw component hashes differ from independently parsed data")
        require(hashlib.sha256(canonical(snapshots[leg])).hexdigest() == profile["mesh_before_sha256"] == profile["mesh_after_sha256"],
                "Recorded aggregate raw snapshot hash differs")
        producer_raw_components[leg] = component_sha

    for name, before in READS.items():
        require(descriptor(Path(name).read_bytes()) == before, "Final private input hash fence differs: " + name)
    result = {
        "passed": True,
        "within_each_leg": within,
        "cross_leg_non_group_components_exact": component_checks,
        "cross_leg_non_group_component_descriptors": component_descriptors,
        "observed_counts": {"nodes": len(baseline["nodes"]), "all_elements": len(baseline["ordered_all_element_ids"]),
                            "volume_elements": len(baseline["volume_connectivity"]),
                            "analysis_group_order_length": len(baseline["ordered_analysis_group"]),
                            "groups": len(baseline_groups)},
        "groups": {"ordered_numeric_handle_lists_identical": True, "unique_numeric_handles_each": len(baseline_ids),
                   "unique_name_type_keys_each": len(baseline_groups), "name_type_to_ordered_membership_bijection_exact": True,
                   "changed_numeric_handle_to_name_type_assignments": handle_reassignments,
                   "named_group_descriptor": named_group_descriptor,
                   "raw_group_component_sha256": {leg: producer_raw_components[leg]["groups"] for leg in LEGS},
                   "normalization": "Across cold legs only: delete id, key groups uniquely by exact(name,element_type). Never sort membership or connectivity."},
        "recorded_native_pins": {"count_each": 63, "maps_exactly_equal": True,
                                 "canonical_recorded_map_descriptor": descriptor(canonical(recorded_pins[0])),
                                 "live_native_paths_read_or_hashed": False},
        "requests": {"raw_bytes_identical": True, "descriptor": descriptor(requests[0])},
        "decks": {"raw_identical": decks[0] == decks[1], "only_differing_line_one_based": timestamp_index + 1,
                  "baseline_timestamp_comment": comments[0][0][1].decode("ascii").rstrip("\n"),
                  "candidate_timestamp_comment": comments[1][0][1].decode("ascii").rstrip("\n"),
                  "all_other_bytes_exact": True, "timestamp_replaced_comparison_only_descriptor": descriptor(normalized_deck)},
        "recorded_raw_snapshot_and_component_hashes_recomputed": True,
        "independently_recomputed_named_group_comparable_snapshot": comparable_descriptor,
        "inputs_unchanged_before_after": True,
        "input_descriptors": READS,
    }
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
