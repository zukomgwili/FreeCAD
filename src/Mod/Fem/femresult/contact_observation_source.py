# SPDX-License-Identifier: LGPL-2.1-or-later
"""Qualify an unchanged native FRD source before contact-side observations.

This adapter reads original solver IDs through the existing FRD reader. It does
not compact nodes, recover a field, interpolate, or declare engineering acceptance.
"""

import hashlib
import json
import math
import os
from pathlib import Path
from decimal import Decimal, InvalidOperation
import re
import stat
import struct

from femtools import force_accounting


def _identity(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _checked_hash(name, *, output=False):
    path = Path(name)
    try:
        if not path.is_absolute() or path.resolve(strict=True) != path:
            raise ValueError("Native source paths must be absolute and must not traverse symlinks.")
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or (output and before.st_nlink != 1):
            raise ValueError(
                "Native source must be a regular file, not a symlink or shared output."
            )
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            identity = _identity(before)
            if _identity(os.fstat(stream.fileno())) != identity:
                raise ValueError("Native source identity changed before hashing.")
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if (
                _identity(os.fstat(stream.fileno())) != identity
                or _identity(path.lstat()) != identity
            ):
                raise ValueError("Native source changed while hashing.")
    except (OSError, TypeError) as error:
        raise ValueError("Native source file is unavailable: " + str(name)) from error
    return {"path": str(path), "sha256": digest}


def _validate_deck(binding):
    raw = Path(binding["path"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != binding["sha256"]:
        raise ValueError("Native movement source deck changed while reading its frame contract.")
    cards = []
    for line in raw.decode("ascii").splitlines():
        text = line.strip().upper()
        if not text or text.startswith("**"):
            continue
        if text.startswith("*"):
            parts = [entry.strip().replace(" ", "") for entry in text[1:].split(",")]
            cards.append((parts[0], parts[1:], []))
        elif cards:
            cards[-1][2].extend(item.strip() for item in text.split(",") if item.strip())
    names = [card[0] for card in cards]
    if "INCLUDE" in names:
        raise ValueError(
            "Unbound deck includes cannot establish native movement source provenance."
        )
    if any(
        name in names
        for name in ("IMPERFECTION", "NMAP", "NCOPY", "NGEN", "NFILL", "SYSTEM", "SUBMODEL")
    ):
        raise ValueError(
            "Initial reference geometry transformations are unsupported for native movement."
        )
    for name, options, values in cards:
        adjustments = [option[7:] for option in options if option.startswith("ADJUST=")]
        if name == "CONTACTPAIR" and any(
            Decimal(value.replace("D", "E")) != 0 for value in adjustments
        ):
            raise ValueError(
                "Nonzero initial contact adjustment changes the original reference geometry."
            )
        if name == "TIE" and adjustments != ["NO"]:
            raise ValueError(
                "Initial tie adjustment must be explicitly disabled for original reference geometry."
            )
    if (
        names.count("STEP") != 1
        or names.count("STATIC") != 1
        or names.count("ENDSTEP") != 1
        or not names.index("STEP") < names.index("STATIC") < names.index("ENDSTEP")
        or any(name in names for name in ("DYNAMIC", "FREQUENCY", "BUCKLE", "STEADYSTATEDYNAMICS"))
    ):
        raise ValueError("Native movement requires exactly one complete static step.")
    step = cards[names.index("STEP")]
    if any(option in ("NLGEOM", "NLGEOM=YES", "PERTURBATION") for option in step[1]):
        raise ValueError("Native movement supports only a small-displacement static step.")
    if names.count("NODEFILE") != 1 or "NODEOUTPUT" in names:
        raise ValueError("Global displacement requires one unambiguous inline NODE FILE request.")
    node_index = names.index("NODEFILE")
    request = cards[node_index]
    # CalculiX noelfiles.f initializes nodesys='G'; GLOBAL=NO selects local
    # components. frdvector.c honors this before emitting the same DISP labels.
    if (
        not names.index("STATIC") < node_index < names.index("ENDSTEP")
        or any(option.startswith("GLOBAL=") and option != "GLOBAL=YES" for option in request[1])
        or "OUTPUT=2D" in request[1]
        or "U" not in request[2]
    ):
        raise ValueError("Native displacement output must explicitly or by default use global XYZ.")


def validate_source(analysis, mesh, accounting_result):
    """Revalidate provenance only, without reading any displacement values."""
    try:
        if not analysis or not mesh or not accounting_result:
            raise ValueError("Select the analysis, original mesh and native accounting source.")
        if (
            analysis.Document is not mesh.Document
            or analysis.Document is not accounting_result.Document
            or mesh not in analysis.Group
            or accounting_result not in analysis.Group
            or not isinstance(accounting_result.Proxy, force_accounting.AccountingResult)
        ):
            raise ValueError(
                "Native accounting source and original mesh must belong to this analysis."
            )
        raw = accounting_result.AccountingData
        data = json.loads(raw)
        if (
            data["schema"] != force_accounting.SCHEMA
            or data["analysis"] != analysis.Name
            or data["mesh"] != mesh.Name
        ):
            raise ValueError(
                "Native accounting identities differ from the selected analysis and mesh."
            )
        source = data.get("movement_source", {})
        if (
            source.get("schema") != force_accounting.MOVEMENT_SOURCE_SCHEMA
            or source.get("status") != "BOUND"
        ):
            raise ValueError("Movement source is unavailable: legacy or unbound native FRD output.")
        for key in ("model_digest", "deck_sha256", "request_sha256", "binary_sha256", "binary"):
            if source[key] != data[key]:
                raise ValueError("Native movement binding differs from accounting: " + key)
        if force_accounting._model_digest(analysis, mesh) != data["model_digest"]:
            raise ValueError("Native movement source is stale after a physical model change.")
        end = data["end_time"]
        if (
            isinstance(end, bool)
            or not isinstance(end, (int, float))
            or not math.isfinite(end)
            or end <= 0
            or source["requested_end_time"] != end
        ):
            raise ValueError("Native movement source requires an exact positive final static time.")
        solvers = [obj for obj in analysis.Group if getattr(obj, "NativeForceAccounting", False)]
        if (
            len(solvers) != 1
            or solvers[0].AnalysisType != "static"
            or solvers[0].GeometricalNonlinearity
            or solvers[0].SplitInputWriter
            or solvers[0].TimePeriod.getValueAs("s").Value != end
        ):
            raise ValueError("Movement source supports one unsplit small-displacement static step.")
        for obj in analysis.Group:
            if (
                obj.isDerivedFrom("Fem::ConstraintContact")
                and obj.Adjust.getValueAs("mm").Value != 0
            ):
                raise ValueError(
                    "Initial contact adjustment is incompatible with original reference geometry."
                )
            if (
                getattr(getattr(obj, "Proxy", None), "Type", "") == "Fem::ConstraintTie"
                and obj.Adjust
            ):
                raise ValueError(
                    "Initial tie adjustment is incompatible with original reference geometry."
                )
        result = {
            "schema": "FREECAD_CONTACT_SOURCE_V1",
            "analysis": analysis.Name,
            "mesh": mesh.Name,
            "accounting": {
                "name": accounting_result.Name,
                "data_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            },
            "model_digest": data["model_digest"],
            "requested_end_time": end,
        }
        for key, path, expected in (
            ("deck", source["deck"], data["deck_sha256"]),
            ("request", source["request"], data["request_sha256"]),
            ("binary", data["binary"], data["binary_sha256"]),
            ("frd", source["path"], source["sha256"]),
        ):
            result[key] = _checked_hash(path, output=key == "frd")
            if result[key]["sha256"] != expected:
                raise ValueError("Native movement source file changed: " + key)
        if Path(result["deck"]["path"]).with_suffix(".accounting") != Path(
            result["request"]["path"]
        ) or Path(result["deck"]["path"]).with_suffix(".frd") != Path(result["frd"]["path"]):
            raise ValueError("Native movement source must use exact deck sibling outputs.")
        _validate_deck(result["deck"])
        return result
    except (
        AttributeError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        UnicodeError,
        OverflowError,
        InvalidOperation,
    ) as error:
        raise ValueError("Incomplete or invalid native movement source provenance.") from error


def _preflight(path, end_time):
    """Reject lossy-reader ambiguities before invoking the native FRD reader."""
    nodes, elements, fields = {}, {}, []
    state = None
    declared = 0
    pending = None
    step = None
    frame = None
    ended = False
    seen_nodes = seen_elements = False
    previous_counter = 0
    previous_time = Decimal(0)
    for line in Path(path).read_text(encoding="ascii").splitlines():
        if not line.strip():
            continue
        if ended:
            raise ValueError("Unexpected records after FRD end marker.")
        if "PMODE" in line:
            raise ValueError("Modal FRD output is not a final static displacement source.")
        if line[4:6] in ("2C", "3C"):
            if state is not None or step is not None or fields:
                raise ValueError("Incomplete or repeated FRD geometry section.")
            parts = line.split()
            if len(parts) != 3 or parts[2] != "1" or int(parts[1]) < 1:
                raise ValueError("Only declared nonempty ASCII FRD geometry is supported.")
            declared = int(parts[1])
            if parts[0] == "2C":
                if seen_nodes:
                    raise ValueError("Duplicate FRD node section.")
                seen_nodes, state = True, "nodes"
            else:
                if seen_elements or not seen_nodes:
                    raise ValueError("Duplicate or out-of-order FRD element section.")
                seen_elements, state = True, "elements"
        elif line[4:10] == "1PSTEP":
            if state is not None or step is not None or not seen_elements:
                raise ValueError("Incomplete FRD block before result frame.")
            parts = line.split()
            if len(parts) != 4 or any(int(value) < 1 for value in parts[1:]):
                raise ValueError("Invalid FRD result step header.")
            step = tuple(map(int, parts[1:]))
            if step[2] != 1 or step[0] <= previous_counter:
                raise ValueError("Ambiguous or nonstatic FRD frame step identities.")
            previous_counter = step[0]
        elif line[2:7] == "100CL":
            if state is not None or step is None or frame is not None:
                raise ValueError("Unbound FRD result state header.")
            literal = line[12:24].strip()
            time = Decimal(literal)
            code = int(line[58:63])
            if (
                len(line) != 75
                or line[74] != "1"
                or line[56:58].strip() != "0"
                or code < 1
                or int(line[7:12]) != 100 + code
                or not time.is_finite()
                or time <= 0
                or time < previous_time
                or time > Decimal(str(end_time))
            ):
                raise ValueError("Unsupported, rounded or nonstatic FRD frame state.")
            previous_time = time
            frame = {
                "step": step,
                "time_literal": literal,
                "time": time,
                "output_increment": code,
                "count": int(line[24:36]),
            }
        elif line.startswith(" -4"):
            if state is not None or frame is None:
                raise ValueError("FRD field has no unique state header.")
            parts = line.split()
            if len(parts) != 4 or int(parts[2]) < 1 or parts[3] != "1":
                raise ValueError("Unsupported FRD field header.")
            frame.update(name=parts[1], declared=int(parts[2]), components=[], ids=set())
            state = "field"
        elif line.startswith(" -5"):
            if state != "field" or frame["ids"]:
                raise ValueError("Misplaced FRD component definition.")
            frame["components"].append(line.split())
        elif line.startswith(" -1"):
            identifier = int(line[3:13])
            if identifier < 1:
                raise ValueError("FRD identities must be positive original solver IDs.")
            if state == "nodes":
                if identifier in nodes:
                    raise ValueError("Duplicate FRD node identity.")
                if len(line) < 49 or line[49:].strip():
                    raise ValueError("Incomplete FRD coordinate record.")
                nodes[identifier] = tuple(
                    line[start : start + 12].strip() for start in (13, 25, 37)
                )
            elif state == "elements":
                if pending is not None:
                    raise ValueError("Incomplete FRD element connectivity.")
                if identifier in elements:
                    raise ValueError("Duplicate FRD element identity.")
                parts = line.split()
                if len(parts) != 5 or int(parts[2]) not in (3, 6):
                    raise ValueError(
                        "Native displacement source supports only Tet4/Tet10 elements."
                    )
                pending = identifier, int(parts[2])
            elif state == "field":
                if identifier in frame["ids"]:
                    raise ValueError("Duplicate FRD field displacement identity.")
                if identifier not in nodes:
                    raise ValueError("FRD field references an unknown node.")
                components = frame["components"]
                if len(components) != frame["declared"]:
                    raise ValueError("Incomplete FRD component definitions.")
                count = sum(component[1] != "ALL" for component in components)
                if len(line) < 13 + 12 * count or line[13 + 12 * count :].strip():
                    raise ValueError("Incomplete FRD field vector record.")
                frame["ids"].add(identifier)
            else:
                raise ValueError("FRD data record outside a declared block.")
        elif line.startswith(" -2"):
            if state != "elements" or pending is None:
                raise ValueError("Unexpected FRD connectivity continuation.")
            identifier, kind = pending
            count = 4 if kind == 3 else 10
            connectivity = tuple(
                int(line[start : start + 10]) for start in range(3, 3 + 10 * count, 10)
            )
            if (
                line[3 + 10 * count :].strip()
                or len(set(connectivity)) != count
                or any(node not in nodes for node in connectivity)
            ):
                raise ValueError("Invalid FRD tetrahedron connectivity.")
            elements[identifier] = kind, connectivity
            pending = None
        elif line.strip() == "-3":
            if state == "nodes" and len(nodes) != declared:
                raise ValueError("FRD declared node count differs from complete records.")
            elif state == "elements" and (len(elements) != declared or pending is not None):
                raise ValueError("FRD declared element count differs from complete records.")
            elif state == "field":
                if len(frame["ids"]) != frame["count"]:
                    raise ValueError("FRD declared field count differs from complete records.")
                fields.append(frame)
                step = frame = None
            elif state not in ("nodes", "elements"):
                raise ValueError("Unexpected FRD block terminator.")
            state = None
        elif line.strip() == "9999":
            if (
                state is not None
                or step is not None
                or not seen_nodes
                or not seen_elements
                or not fields
            ):
                raise ValueError("Incomplete FRD before end marker.")
            ended = True
        elif not (line.strip() == "1C" or line.startswith("    1U")):
            raise ValueError("Unsupported or misplaced FRD control record.")
    if not ended:
        raise ValueError("Missing complete FRD end marker.")
    return nodes, elements, fields


def _final_frame(fields, physical_nodes, end_time):
    final = []
    definitions = [
        ["-5", "D1", "1", "2", "1", "0"],
        ["-5", "D2", "1", "2", "2", "0"],
        ["-5", "D3", "1", "2", "3", "0"],
        ["-5", "ALL", "1", "2", "0", "0", "1ALL"],
    ]
    for field in fields:
        if field["name"] in ("DISPI", "PDISP", "MDISP"):
            raise ValueError("Unsupported nonstatic or imaginary displacement frame.")
        if field["name"] != "DISP":
            continue
        if field["components"] != definitions:
            raise ValueError("Unsupported displacement component definitions.")
        if field["time"] == Decimal(str(end_time)):
            final.append(field)
    if len(final) != 1:
        raise ValueError("Native FRD must contain one unambiguous exact final displacement frame.")
    if not set(physical_nodes).issubset(final[0]["ids"]):
        raise ValueError("Final displacement frame omits original physical node values.")
    return final[0]


def _verify_geometry(mesh, nodes, elements):
    native = mesh.FemMesh
    original_nodes = native.Nodes
    if not original_nodes or not set(original_nodes).issubset(nodes):
        raise ValueError("FRD coordinates omit original physical mesh nodes.")
    for node, point in original_nodes.items():
        for coordinate, literal in zip(point, nodes[node]):
            if not math.isfinite(coordinate) or not re.fullmatch(
                r"[+-]?\d\.\d{5}E[+-]\d{2}", literal
            ):
                raise ValueError("Nonfinite or unsupported native FRD coordinate literal.")
            # CalculiX frd.c prints (float)co with %12.5E. Qualify that exact
            # binary32 conversion and half of the literal's decimal quantum;
            # never replace the original native double-coordinate geometry.
            try:
                rounded = struct.unpack("!f", struct.pack("!f", coordinate))[0]
                printed = Decimal(literal)
                difference = abs(Decimal.from_float(rounded) - printed)
                half_quantum = Decimal(1).scaleb(printed.as_tuple().exponent) / 2
                roundoff = Decimal.from_float(math.ulp(rounded)) * 2
            except (OverflowError, InvalidOperation) as error:
                raise ValueError(
                    "Original coordinate is outside supported FRD precision."
                ) from error
            if (
                not math.isfinite(rounded)
                or (printed == 0 and rounded != 0)
                or difference > half_quantum + roundoff
            ):
                raise ValueError(
                    "FRD coordinate differs from the original mesh beyond native printing bounds."
                )
    volumes = set(native.Volumes)
    if not volumes or set(elements) != volumes:
        raise ValueError("FRD volume identities differ from original mesh topology.")
    for identifier in volumes:
        connectivity = tuple(native.getElementNodes(identifier))
        kind, frd_connectivity = elements[identifier]
        if (
            len(connectivity) not in (4, 10)
            or len(set(connectivity)) != len(connectivity)
            or len(connectivity) != (4 if kind == 3 else 10)
            or set(connectivity) != set(frd_connectivity)
        ):
            raise ValueError("FRD volume topology differs from the original Tet4/Tet10 mesh.")


def _load_source(analysis, mesh, accounting_result):
    from feminout.importCcxFrdResults import read_frd_result

    source = validate_source(analysis, mesh, accounting_result)
    # Keep process-local file identities across the entire preflight/decode,
    # not only across each hash read. A writer can change the values read by the
    # native decoder and restore the original bytes before the final hash.
    # Do not persist these snapshots: unchanged cold history may legitimately
    # have different filesystem identities when explicitly revalidated.
    file_states = {
        key: _identity(Path(source[key]["path"]).lstat())
        for key in ("deck", "request", "binary", "frd")
    }
    sidecar = (
        Path(source["frd"]["path"])
        .with_suffix("")
        .with_name(Path(source["frd"]["path"]).stem + "_inout_nodes.txt")
    )
    if os.path.lexists(sidecar):
        raise ValueError("Unbound native reader sidecar is unsupported for static displacement.")
    nodes, elements, fields = _preflight(source["frd"]["path"], source["requested_end_time"])
    _verify_geometry(mesh, nodes, elements)
    final = _final_frame(fields, mesh.FemMesh.Nodes, source["requested_end_time"])
    parsed = read_frd_result(source["frd"]["path"])
    topology = {**parsed["Tetra4Elem"], **parsed["Tetra10Elem"]}
    if (
        set(parsed["Nodes"]) != set(nodes)
        or set(topology) != set(mesh.FemMesh.Volumes)
        or any(
            tuple(mesh.FemMesh.getElementNodes(identifier)) != connectivity
            for identifier, connectivity in topology.items()
        )
    ):
        # The existing native reader already converts FRD tetrahedral ordering
        # back to FreeCAD's native corner and midside ordering. Do not duplicate
        # that conversion here or accept merely equal unordered node sets.
        raise ValueError("Native FRD ordered topology differs from the original mesh.")
    frames = [
        row
        for row in parsed["Results"]
        if row.get("time") == source["requested_end_time"] and "disp" in row
    ]
    if len(frames) != 1:
        raise ValueError("Native FRD must contain one unambiguous final displacement frame.")
    values = {node: tuple(frames[0]["disp"][node]) for node in mesh.FemMesh.Nodes}
    if not all(
        len(row) == 3 and all(math.isfinite(component) for component in row)
        for row in values.values()
    ):
        raise ValueError("Native FRD contains nonfinite physical displacement.")
    if validate_source(analysis, mesh, accounting_result) != source:
        raise ValueError("Native movement source changed while parsing.")
    if any(
        _identity(Path(source[key]["path"]).lstat()) != before
        for key, before in file_states.items()
    ):
        raise ValueError("Native movement source file identity changed while parsing.")
    source["observed_time"] = frames[0]["time"]
    source["physical_node_count"] = len(values)
    source["volume_count"] = len(elements)
    source["field_frame"] = {
        "step": final["step"][2],
        "increment": final["step"][1],
        "result_index": final["step"][0],
        "output_increment": final["output_increment"],
        "name": "DISP",
        "components": ["D1", "D2", "D3"],
        "units": "mm",
        "frame": "Global Cartesian XYZ",
        "storage": "Native ASCII FRD: binary32 cast, %12.5E components; not full solver precision",
        "geometry": "Original native double coordinates; FRD coordinates only validate source identity",
    }
    return values, source


def load_source(analysis, mesh, accounting_result):
    """Return original-node global Cartesian displacement in mm and exact source identity."""
    try:
        return _load_source(analysis, mesh, accounting_result)
    except (
        OSError,
        UnicodeError,
        InvalidOperation,
        OverflowError,
        KeyError,
        IndexError,
        TypeError,
    ) as error:
        raise ValueError("Incomplete, malformed or unsupported native FRD source.") from error
