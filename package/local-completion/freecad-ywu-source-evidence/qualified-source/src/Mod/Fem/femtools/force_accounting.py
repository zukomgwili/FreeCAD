# SPDX-License-Identifier: LGPL-2.1-or-later
"""Versioned native accounting interface; no force recovery/integration in Python.

The opt-in solver uses actual consistent element loads and contact nodal forces.
Cut wrenches are equilibrium-derived on an explicitly owned free body. They are
not SOF/SOM, and agreement with equilibrium is not stress/design acceptance.
V2 adds the net native MPC action on each explicitly owned cut body, separately
from LOAD and CONTACT. It is not a per-Tie multiplier or a projected RF value.
V3 separates selected physical external supports from moving internal RBE
scalar-connector ports. Ordinary zero Fixed/Displacement translations may be
selected outside cut bodies; internal ports are not reported as supports.
The solver rejects prescribed body DOFs, shared-node MPC participation and
cut-node point loads. Literal V1/V2 output remains readable; V1 has no MPC channel.
"""

import hashlib
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from types import SimpleNamespace

import FreeCAD

from femmesh import meshtools
from femmesh import quality
from femobjects.base_fempythonobject import BaseFemPythonObject
from femtools.elastic_connector import rigid_body_node_ids
from femtools.elastic_connector import rigid_body_nodes
from femtools.native_properties import property_value


SCHEMA = "CCX_FORCE_ACCOUNTING_V3"
V2_SCHEMA = "CCX_FORCE_ACCOUNTING_V2"
LEGACY_SCHEMA = "CCX_FORCE_ACCOUNTING_V1"
MOVEMENT_SOURCE_SCHEMA = "FREECAD_MOVEMENT_SOURCE_V1"
_reports = {}
_FACE_NODES = {
    4: ((0, 1, 2), (0, 3, 1), (1, 3, 2), (2, 3, 0)),
    10: (
        (0, 1, 2, 4, 5, 6),
        (0, 3, 1, 7, 8, 4),
        (1, 3, 2, 8, 9, 5),
        (2, 3, 0, 9, 7, 6),
    ),
}


def enabled(solver):
    return bool(getattr(solver, "NativeForceAccounting", False))


def solver_binary(solver):
    explicit = str(solver.NativeAccountingSolver)
    return explicit or str(
        Path(FreeCAD.ConfigGet("AppHomePath")) / "data" / "NativeSolvers" / "ccx-force-accounting"
    )


def require_capability(binary):
    try:
        result = subprocess.run(
            [str(binary), "--freecad-force-accounting-version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("Qualified native force-accounting solver is unavailable.") from error
    if result.returncode != 0 or result.stdout.strip() != SCHEMA:
        raise ValueError(
            "Solver does not implement native force accounting V3; "
            "select the qualified bundled solver or disable NativeForceAccounting."
        )


def _sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class _RunMetadata(dict):
    """Accounting metadata with non-serialized, process-lifetime output custody."""


def _file_identity(info, *, changed_time=True):
    identity = (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
    )
    return identity + (info.st_ctime_ns,) if changed_time else identity


def _prepare_movement_run(deck):
    # Use the exact generated sibling, never a wildcard or a user-selected result.
    path = Path(deck).parent.resolve(strict=True) / Path(deck).with_suffix(".frd").name
    state = {"path": str(path), "finished": False, "returncode": None}
    try:
        previous = path.lstat()
    except FileNotFoundError:
        return state
    if not stat.S_ISREG(previous.st_mode) or previous.st_nlink != 1:
        raise ValueError("Generated FRD output must be a regular, unshared file, not a symlink.")
    recovery = Path(tempfile.mkdtemp(prefix="." + path.stem + "-previous-frd-", dir=path.parent))
    saved = recovery / path.name
    path.replace(saved)
    state["recovery_path"] = str(saved)
    if _file_identity(saved.lstat(), changed_time=False) != _file_identity(
        previous, changed_time=False
    ):
        # The exact file remains recoverable even if a competing writer raced us.
        raise ValueError("Previous FRD changed during quarantine; inspect the recovery directory.")
    return state


def _capture_movement(path):
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not before.st_size:
            raise ValueError("Fresh FRD must be a nonempty regular, unshared file.")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            identity = _file_identity(before)
            if _file_identity(os.fstat(stream.fileno())) != identity:
                raise ValueError("Fresh FRD identity changed before hashing.")
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if (
                _file_identity(os.fstat(stream.fileno())) != identity
                or _file_identity(path.lstat()) != identity
            ):
                raise ValueError("Fresh FRD changed while hashing.")
        return {"sha256": digest, "identity": identity}
    except FileNotFoundError:
        return {"reason": "Successful solver run produced no fresh FRD."}
    except (OSError, ValueError) as error:
        return {"reason": str(error)}


def finish_run(context, returncode):
    """Record an actual completed child process before importing its accounting.

    This is in-process custody, not an attestation for arbitrary external files.
    Only the solver subprocess owner calls this after communicate has completed.
    Legacy accounting contexts remain supported without displacement provenance.
    """
    if context is not None:
        state = getattr(context[1], "movement_run", None)
        if state is not None and not state["finished"]:
            state.update(finished=True, returncode=returncode)
            if returncode == 0:
                state["completed_file"] = _capture_movement(Path(state["path"]))


def _movement_source(metadata, deck):
    path = Path(deck).parent.resolve(strict=True) / Path(deck).with_suffix(".frd").name
    source = {
        "schema": MOVEMENT_SOURCE_SCHEMA,
        "status": "UNAVAILABLE",
        "domain": "Fresh run-owned FRD bytes, not qualified displacement or design acceptance",
        "path": str(path),
        "deck": str(Path(deck).resolve()),
        "request": str(Path(deck).with_suffix(".accounting").resolve()),
        "requested_end_time": metadata["end_time"],
        "time_basis": "Requested final static time; field reader must verify actual FRD state",
        **{
            key: metadata[key]
            for key in ("deck_sha256", "request_sha256", "binary_sha256", "model_digest", "binary")
        },
    }
    state = getattr(metadata, "movement_run", None)
    if state is None:
        source["reason"] = "Legacy accounting context has no fresh solver-run FRD custody."
    else:
        if "recovery_path" in state:
            source["recovery_path"] = state["recovery_path"]
        if not state["finished"] or state["returncode"] != 0:
            source["reason"] = "No successful completed solver run owns this FRD."
        else:
            completed = state["completed_file"]
            current = _capture_movement(path)
            if "reason" in completed:
                source["reason"] = completed["reason"]
            elif completed != current:
                source["reason"] = "Fresh FRD changed after solver completion."
            else:
                source.update(status="BOUND", sha256=current["sha256"])
    return source


def _is_result(obj):
    # The stock FRD/DAT import also adds post-processing pipelines and a text
    # document to the analysis. Like the nodal result, these are outputs, not
    # mechanical inputs. Importing them must not invalidate the owning run.
    if any(
        obj.isDerivedFrom(kind)
        for kind in ("Fem::FemResultObject", "Fem::FemPostObject", "App::TextDocument")
    ) or ("Proxy" in obj.PropertiesList and isinstance(obj.Proxy, AccountingResult)):
        return True
    if "Proxy" in obj.PropertiesList:
        # Sample observations are not mechanical nodal result objects, but are
        # still outputs and must never participate in the physical input digest.
        from femobjects.mesh_result import MeshResult
        from femobjects.result_contact_observation import ContactObservationResult

        return isinstance(obj.Proxy, (ContactObservationResult, MeshResult))
    return False


def _model_digest(analysis, mesh):
    seen = set()

    def value(item):
        if hasattr(item, "PropertiesList") and hasattr(item, "Name"):
            if _is_result(item):
                return None
            if item.Name in seen:
                return item.Name
            seen.add(item.Name)
            shape = (
                meshtools.get_mesh_geometry_signature(item)
                if "Shape" in item.PropertiesList and hasattr(item.Shape, "exportBrepToString")
                else None
            )
            return {
                "name": item.Name,
                "type": item.TypeId,
                "geometry": shape,
                "properties": {
                    key: value(item.getPropertyByName(key))
                    for key in sorted(item.PropertiesList)
                    if key
                    not in (
                        "Proxy",
                        "Shape",
                        "FemMesh",
                        "ExpressionEngine",
                        "Label",
                        "WorkingDir",
                        "WorkingDirectory",
                    )
                    and item.getGroupOfProperty(key) != "Mesh Quality"
                },
            }
        if isinstance(item, dict):
            return {str(key): value(entry) for key, entry in sorted(item.items())}
        if isinstance(item, (tuple, list)):
            return [
                value(entry)
                for entry in item
                if not (hasattr(entry, "PropertiesList") and _is_result(entry))
            ]
        return property_value(item)

    state = [quality.input_fingerprint(mesh), value(analysis)]
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


def _connectivity(path, springs=()):
    elements, count, pending = {}, 0, []
    expected_springs = {row["element"]: list(row["nodes"]) for row in springs}
    if len(expected_springs) != len(springs):
        raise ValueError("Duplicate native scalar spring identity.")
    found_springs, seen, kind = set(), set(), ""
    for line in Path(path).read_text().splitlines():
        text = line.strip()
        if not text or text.startswith("**"):
            continue
        if text.startswith("*"):
            if pending:
                raise ValueError("Incomplete native element connectivity.")
            count = 0
            if text.upper().startswith("*ELEMENT,"):
                fields = text.upper().replace(" ", "").split(",")
                kind = next((field[5:] for field in fields if field.startswith("TYPE=")), "")
                if kind not in ("C3D4", "C3D10", "SPRING2") or (
                    kind == "SPRING2" and not expected_springs
                ):
                    raise ValueError("Native force accounting requires only C3D4/C3D10 volumes.")
                count = {"C3D4": 4, "C3D10": 10, "SPRING2": 2}[kind]
        elif count:
            pending.extend(int(item.strip()) for item in text.split(",") if item.strip())
            if len(pending) == count + 1:
                if pending[0] in seen:
                    raise ValueError("Duplicate native element identity.")
                seen.add(pending[0])
                if kind == "SPRING2":
                    if expected_springs.get(pending[0]) != pending[1:]:
                        raise ValueError(
                            "Scalar spring connectivity differs from the stock writer."
                        )
                    found_springs.add(pending[0])
                else:
                    elements[pending[0]] = pending[1:]
                pending = []
            elif len(pending) > count + 1:
                raise ValueError("Invalid native element connectivity.")
    if pending:
        raise ValueError("Incomplete native element connectivity.")
    if found_springs != set(expected_springs):
        raise ValueError("Declared scalar spring is missing from the stock deck.")
    return elements


def prepare_request(writer):
    """Write an opt-in request from exact writer IDs and current CAD group provenance."""
    solver, mesh, analysis = writer.solver_obj, writer.mesh_object, writer.analysis
    if not enabled(solver):
        if any(
            getattr(row["Object"], "NativeEquilibriumCut", False)
            for row in writer.member.cons_sectionprint
        ):
            raise ValueError(
                "Enable NativeForceAccounting on the solver to request NativeEquilibriumCut."
            )
        return
    if solver.AnalysisType != "static" or solver.GeometricalNonlinearity or solver.SplitInputWriter:
        raise ValueError(
            "Native force accounting requires an unsplit small-displacement static deck."
        )
    springs = getattr(writer, "native_accounting_springs", ())
    for spring in springs:
        if spring["kind"] != "SPRING2" or len(spring["bodies"]) != 2:
            raise ValueError(
                "Native accounting supports two-point scalar connectors on explicit RBE ports, "
                "not ground or direct solid-node springs."
            )
    elements = _connectivity(writer.file_name, springs)
    lines, expected = [SCHEMA], []
    support_regions, selected_rigid_regions = set(), set()
    rigid_rows = {row["Object"]: row for row in writer.member.cons_rigidbody}
    fixed_rows = {row["Object"]: row for row in writer.member.cons_fixed}
    displacement_rows = {row["Object"]: row for row in writer.member.cons_displacement}
    ordinary_rows = {**fixed_rows, **displacement_rows}
    selected = list(getattr(solver, "NativeAccountingSupports", ())) or list(rigid_rows)
    if len(selected) != len(set(selected)):
        raise ValueError("Native accounting support selection contains duplicates.")
    if any(body not in rigid_rows and body not in ordinary_rows for body in selected):
        raise ValueError(
            "Selected native accounting support is not a supported analysis constraint."
        )
    for row in writer.member.cons_rigidbody:
        body = row["Object"]
        ref, rot = rigid_body_node_ids(analysis, mesh, body)
        nodes = rigid_body_nodes(body, mesh)
        if support_regions.intersection(nodes):
            raise ValueError(
                "Native accounting requires disjoint RBE regions, not duplicate ports."
            )
        support_regions.update(nodes)
        lines.append(f"PORT {body.Name} {ref} {rot}")
        if body not in selected:
            continue
        selected_rigid_regions.update(nodes)
        if (
            any(
                getattr(body, kind + "Mode" + axis) != "Constraint"
                for kind in ("Translational", "Rotational")
                for axis in "XYZ"
            )
            or body.Displacement.Length != 0
            or body.Rotation.Angle != 0
            or body.EnableAmplitude
        ):
            raise ValueError(
                f"{body.Name}: accounting supports must have all six motions prescribed at zero."
            )
        lines.append(f"SUPPORT {body.Name} {ref} {rot}")
        expected.append(("SUPPORT", body.Name))
    # Use the same physical nodes and directions as the stock boundary writer,
    # not inferred reactions on all fixed/helper nodes. Check attribution
    # against *all* ordinary constraints: even an unselected duplicate would
    # make a selected constraint's reaction ambiguous after native SPC merging.
    terms_by_support, dof_owner = {}, {}
    for obj, row in ordinary_rows.items():
        directions = (
            [1, 2, 3]
            if obj in fixed_rows
            else [index for index, axis in enumerate("xyz", 1) if not getattr(obj, axis + "Free")]
        )
        terms = [(node, direction) for node in row["Nodes"] for direction in directions]
        if any(node in selected_rigid_regions for node, direction in terms):
            raise ValueError(
                "Ordinary physical supports must not overlap a selected external RBE receiving region."
            )
        terms_by_support[obj] = terms
        for term in terms:
            if term in dof_owner and (obj in selected or dof_owner[term] in selected):
                raise ValueError("Native accounting physical support degrees of freedom overlap.")
            dof_owner[term] = obj
    for obj in selected:
        if obj not in ordinary_rows:
            continue
        terms = terms_by_support[obj]
        if solver.ModelSpace != "3D" or not terms:
            raise ValueError(f"{obj.Name}: select nonempty ordinary 3D support translations.")
        if obj in displacement_rows and (
            obj.EnableAmplitude
            or any(
                not getattr(obj, axis + "Free")
                and getattr(obj, axis + "Displacement").getValueAs("mm").Value != 0
                for axis in "xyz"
            )
        ):
            raise ValueError(
                f"{obj.Name}: accounting requires zero support motions without amplitude."
            )
        if any(node in support_regions for node, direction in terms):
            raise ValueError("Ordinary physical supports must not overlap an RBE receiving region.")
        lines.append(f"SPC_SUPPORT {obj.Name} {len(terms)}")
        lines.extend(f"{node} {direction}" for node, direction in sorted(terms))
        expected.append(("SUPPORT", obj.Name))
    for spring in springs:
        for auxiliary, rotation, axis in spring["angles"]:
            lines.append(
                f"ANGLE {auxiliary} {rotation} " + " ".join(f"{value:.12e}" for value in axis)
            )
        lines.append(f"SPRING {spring['element']} " + " ".join(map(str, spring["nodes"])))
    for row in writer.member.cons_sectionprint:
        obj = row["Object"]
        if not getattr(obj, "NativeEquilibriumCut", False):
            continue
        if obj.Variable != "Section Force" or not obj.AccountingBody:
            raise ValueError(
                f"{obj.Name}: select the explicit solid AccountingBody for a Section Force cut."
            )
        selector = SimpleNamespace(Name=obj.Name, References=obj.AccountingBody)
        owned = meshtools._get_solid_reference_group_sets(
            mesh, [{"Object": selector}], set(mesh.FemMesh.Volumes)
        )
        if owned is None:
            raise ValueError(
                "Native equilibrium cuts require current CAD entity groups; regenerate the mesh."
            )
        volumes = sorted({element for reference, group, sub in owned[0] for element in group})
        cut = set()
        for reference, faces, sub in row["SectionPrintFaces"]:
            if not sub:
                raise ValueError("Native equilibrium cuts require solid element facets.")
            for element, face in faces:
                if element not in volumes:
                    raise ValueError(
                        "AccountingBody must own the selected one-sided facets; do not fit signs."
                    )
                nodes = elements[element]
                cut.update(nodes[index] for index in _FACE_NODES[len(nodes)][face - 1])
        if not volumes or not cut:
            raise ValueError(f"{obj.Name}: empty accounting body or cut.")
        lines.extend(
            [
                f"BODY {obj.Name} {len(volumes)} {len(cut)}",
                " ".join(map(str, volumes)),
                " ".join(map(str, sorted(cut))),
            ]
        )
        expected.append(("CUT", obj.Name))
    if not expected:
        raise ValueError("No physical support or NativeEquilibriumCut was selected for accounting.")
    lines.append("END")
    path = Path(writer.file_name).with_suffix(".accounting")
    path.write_text("\n".join(lines) + "\n")
    metadata = {
        "schema": SCHEMA,
        "expected": expected,
        "deck_sha256": _sha(writer.file_name),
        "request_sha256": _sha(path),
        "model_digest": _model_digest(analysis, mesh),
        "analysis": analysis.Name,
        "mesh": mesh.Name,
        "end_time": solver.TimePeriod.getValueAs("s").Value,
    }
    Path(str(path) + ".json").write_text(json.dumps(metadata, sort_keys=True))


def parse_output(text, expected, end_time, *, schema=None):
    lines = [line.split() for line in text.splitlines() if line.strip()]
    if (
        len(lines) < 4
        or lines[0] not in ([SCHEMA], [V2_SCHEMA], [LEGACY_SCHEMA])
        or (schema is not None and lines[0] != [schema])
        or lines[-1] != ["END"]
    ):
        raise ValueError("Missing, incomplete or unsupported native accounting output.")
    state = lines[1]
    if (
        len(state) != 4
        or state[0] != "STATE"
        or int(state[1]) != 1
        or int(state[2]) < 1
        or not math.isclose(float(state[3]), end_time, rel_tol=1e-10, abs_tol=1e-12)
    ):
        raise ValueError("Native accounting output is not at the requested final state.")
    channels = ("LOAD", "CONTACT") if lines[0] == [LEGACY_SCHEMA] else ("LOAD", "CONTACT", "MPC")
    result = {kind: {} for kind in ("SUPPORT", "CUT", *channels)}
    for row in lines[2:-1]:
        if len(row) != 8 or row[0] not in result or row[1] in result[row[0]]:
            raise ValueError("Invalid or duplicate native accounting row.")
        values = list(map(float, row[2:]))
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Nonfinite native accounting wrench.")
        result[row[0]][row[1]] = values
    actual = {(kind, name) for kind in ("SUPPORT", "CUT") for name in result[kind]}
    if actual != set(expected):
        raise ValueError("Native accounting output identities differ from the current request.")
    cuts = set(result["CUT"])
    if any(set(result[kind]) != cuts for kind in channels):
        raise ValueError("Native cut load/contact/MPC accounting is incomplete.")
    for name in cuts:
        for terms in zip(result["CUT"][name], *(result[kind][name] for kind in channels)):
            if abs(math.fsum(terms)) > 1e-12 * max(1, *(abs(value) for value in terms)):
                raise ValueError("Native cut/load/contact/MPC channels are inconsistent.")
    return result


def run_context(fea, binary):
    """Validate current provenance and return a per-process environment/context."""
    if not enabled(fea.solver):
        return None
    require_capability(binary)
    path = Path(fea.inp_file_name).with_suffix(".accounting")
    try:
        metadata = json.loads(Path(str(path) + ".json").read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(
            "Accounting request metadata is unavailable; rewrite the solver input."
        ) from error
    if metadata.get("schema") != SCHEMA:
        raise ValueError("Accounting contract changed; rewrite the solver deck and request.")
    if (
        metadata["deck_sha256"] != _sha(fea.inp_file_name)
        or metadata["request_sha256"] != _sha(path)
        or metadata["model_digest"] != _model_digest(fea.analysis, fea.mesh)
    ):
        raise ValueError("Accounting inputs changed; rewrite the solver deck and request.")
    output = Path(str(path) + ".out")
    if output.exists():
        output.unlink()  # exact generated output, never an input or a project document
    environment = dict(os.environ)
    environment.pop("CCX_9ZT_DIAGNOSTIC", None)
    environment["CCX_FORCE_ACCOUNTING_REQUEST"] = str(path.resolve())
    metadata = _RunMetadata(metadata)
    metadata["binary_sha256"] = _sha(binary)
    metadata["binary"] = str(Path(binary).resolve())
    metadata.movement_run = _prepare_movement_run(fea.inp_file_name)
    return environment, metadata, output


def import_result(fea, context):
    environment, metadata, output = context
    request = Path(fea.inp_file_name).with_suffix(".accounting")
    current = {
        "model_digest": _model_digest(fea.analysis, fea.mesh),
        "deck_sha256": _sha(fea.inp_file_name),
        "request_sha256": _sha(request),
        "binary_sha256": _sha(metadata["binary"]),
    }
    mismatches = [name for name, value in current.items() if metadata[name] != value]
    if mismatches:
        raise ValueError(
            "Accounting provenance changed while solving ("
            + ", ".join(mismatches)
            + "); native accounting is historical, not current."
        )
    schema = metadata.get("schema", LEGACY_SCHEMA)
    if schema not in (SCHEMA, V2_SCHEMA, LEGACY_SCHEMA):
        raise ValueError("Unsupported native accounting request schema.")
    values = parse_output(
        output.read_text(),
        {tuple(item) for item in metadata["expected"]},
        metadata["end_time"],
        schema=schema,
    )
    v2 = schema != LEGACY_SCHEMA
    metadata.update(
        schema=schema,
        movement_source=_movement_source(metadata, fea.inp_file_name),
        wrenches=values,
        output_sha256=_sha(output),
        units="N and Nmm",
        method=(
            "Native support residual; separate native LOAD/CONTACT/MPC equilibrium-derived cut"
            if v2
            else "Native support residual; native LOAD/CONTACT equilibrium-derived cut (V1)"
        ),
        frame=(
            "Global Cartesian, original reference-state nodal application positions"
            if v2
            else "Global Cartesian, V1 native reference positions; contact adjustment not qualified"
        ),
        limitations="One small-displacement static step, Tet4/Tet10, "
        + (
            "selected zero-motion RBE supports or ordinary zero prescribed translations "
            "outside cut bodies; moving internal RBE ports with positive linear two-port "
            "scalar connectors; "
            if schema == SCHEMA
            else "zero-motion RBE supports, "
        )
        + (
            "acyclic translational MPCs on body-exclusive nodes, optional face-to-face "
            "penalty contact; no per-Tie multipliers, changed reference coordinates, "
            if v2
            else "face-to-face penalty contact; no MPC cut bodies, "
        )
        + "stress/design acceptance or mesh-accuracy guarantee",
    )
    obj = make_result(fea.analysis)
    obj.AccountingData = json.dumps(metadata, sort_keys=True)
    obj.Resultants = [
        f"{kind} {name}: F(N)={row[:3]}; M_origin(Nmm)={row[3:]}"
        for kind in ("SUPPORT", "CUT")
        for name, row in values[kind].items()
    ]
    obj.Status = "Current native accounting; not design acceptance"
    return obj


class AccountingResult(BaseFemPythonObject):
    Type = "Fem::NativeForceAccountingResult"

    def __init__(self, obj):
        super().__init__(obj)
        _reports.setdefault(obj.Document.Name, set()).add(obj.Name)

    def onDocumentRestored(self, obj):
        _reports.setdefault(obj.Document.Name, set()).add(obj.Name)
        obj.Status = "Stale after restore; rerun to establish current native accounting"


def make_result(analysis):
    obj = analysis.Document.addObject("App::FeaturePython", "NativeForceAccounting")
    AccountingResult(obj)
    obj.Label = "Native force accounting (N, Nmm)"
    for kind, name, doc in (
        (
            "App::PropertyString",
            "Status",
            "Current or historical accounting; never structural design acceptance",
        ),
        (
            "App::PropertyStringList",
            "Resultants",
            "Global force and original-state global-origin moment",
        ),
        (
            "App::PropertyString",
            "AccountingData",
            "Native channels, exact input/binary hashes and applicability",
        ),
    ):
        obj.addProperty(kind, name, "Native Force Accounting", doc)
        obj.setPropertyStatus(name, "LockDynamic")
        obj.setEditorMode(name, 1)
    analysis.addObject(obj)
    return obj


class _Observer:
    def slotChangedObject(self, obj, prop):
        if obj.Document is None or _is_result(obj):
            return
        for name in tuple(_reports.get(obj.Document.Name, ())):
            result = obj.Document.getObject(name)
            if result is None or not getattr(result, "Status", "").startswith("Current"):
                continue
            metadata = json.loads(result.AccountingData or "{}")
            analysis = obj.Document.getObject(metadata.get("analysis", ""))
            mesh = obj.Document.getObject(metadata.get("mesh", ""))
            if (
                not analysis
                or not mesh
                or metadata.get("model_digest") != _model_digest(analysis, mesh)
            ):
                result.Status = "Stale after model change; rerun native accounting"

    def slotDeletedObject(self, obj):
        if obj.Document is not None and not _is_result(obj):
            for name in tuple(_reports.get(obj.Document.Name, ())):
                result = obj.Document.getObject(name)
                if result is not None and getattr(result, "Status", "").startswith("Current"):
                    result.Status = "Stale after model deletion; rerun native accounting"

    def slotDeletedDocument(self, doc):
        _reports.pop(doc.Name, None)


_observer = _Observer()
FreeCAD.addDocumentObserver(_observer)
