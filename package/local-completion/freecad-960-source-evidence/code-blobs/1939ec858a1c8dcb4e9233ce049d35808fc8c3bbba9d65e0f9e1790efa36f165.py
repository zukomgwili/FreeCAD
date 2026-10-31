# SPDX-License-Identifier: LGPL-2.1-or-later
"""Owned native beam-end observations, never stress recovery or nodal averaging.

The solver observer retains element/end identities and the actual expanded
section basis before the legacy FRD nodal average. Reference beam orientations
are provenance, not replacements for the observed current face basis.
"""

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import uuid

import FreeCAD as App
from femobjects.base_fempythonobject import BaseFemPythonObject

SCHEMA = "CCX_BEAM_SECTION_V1"
ENV = "CCX_BEAM_SECTION_REQUEST"
UNITS = {"length": "mm", "force": "N", "moment": "N*mm"}
_latest = {}
_completed = {}


def enabled(solver):
    return bool(getattr(solver, "BeamSectionForces", False))


def _read(path):
    from femtools.contact_state import _capture

    path = Path(path)
    if path.lstat().st_nlink != 1:
        raise ValueError("Beam section source must be a regular, unshared file")
    return _capture(path)


def _sha(path):
    return _read(path)[1]


def _json(literal):
    from femtools.contact_state import _json as strict_json

    return strict_json(literal)


def _model(analysis, mesh):
    from femtools.contact_state import _model as physical_model

    return physical_model(analysis, mesh)


def _binary(solver):
    from femtools.force_accounting import solver_binary

    return str(Path(solver_binary(solver)).resolve(strict=True))


def require_capability(binary):
    env = dict(os.environ)
    env.pop(ENV, None)
    try:
        with tempfile.TemporaryDirectory(prefix="freecad-beam-version-") as directory:
            result = subprocess.run(
                [str(binary), "--freecad-beam-section-version"],
                cwd=directory,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=10,
                text=True,
                check=False,
            )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("Qualified native beam-end observer is unavailable") from error
    if result.returncode != 0 or result.stdout.strip() != SCHEMA:
        raise ValueError("Solver lacks native beam-end output V1; select the qualified solver")


def _request_path(deck):
    return Path(deck).with_suffix(".beam-section")


def is_section_output(filename):
    """Never reinterpret known resultant files as stress after a flag change."""
    result = Path(filename)
    request = _request_path(result)
    if any(path.exists() or path.is_symlink() for path in (request, Path(str(request) + ".json"))):
        return True
    deck = result.with_suffix(".inp")
    if deck.exists() or deck.is_symlink():
        return "SECTION FORCES" in _read(deck)[0].decode("utf-8").upper()
    return False


def _results(analysis):
    return [
        obj
        for obj in analysis.Group
        if isinstance(getattr(obj, "Proxy", None), BeamSectionForceResult)
    ]


def invalidate(analysis, reason):
    key = (analysis.Document.Name, analysis.Name)
    _latest[key] = None
    _completed.pop(key, None)
    for obj in _results(analysis):
        obj.Proxy._updating = True
        try:
            obj.CompletedRun = False
            obj.Status = "Stale: " + reason
        finally:
            obj.Proxy._updating = False


def preflight(analysis, solver, mesh):
    if not enabled(solver):
        return
    if (
        solver.AnalysisType != "static"
        or solver.GeometricalNonlinearity
        or solver.MaterialNonlinearity
        or solver.SplitInputWriter
        or solver.ModelSpace != "3D"
    ):
        raise ValueError(
            "Beam section output requires an unsplit linear small-displacement static step"
        )
    if solver.Output3d:
        raise ValueError("Beam section forces require Output3d=False")
    if not solver.ReducedIntegration or solver.ExcludeBendingStiffness:
        raise ValueError(
            "Beam section output requires native B32R beams, not trusses or full integration"
        )
    if getattr(solver, "NativeForceAccounting", False) or getattr(
        solver, "NativeContactOutputs", ()
    ):
        raise ValueError(
            "Beam section output is separate from solid accounting/contact diagnostics"
        )
    if mesh is None or mesh.Document != analysis.Document or solver.Document != analysis.Document:
        raise ValueError("Beam section output requires same-document analysis, solver and mesh")
    if mesh not in analysis.Group or solver not in analysis.Group:
        raise ValueError("Select an active beam mesh and solver in this analysis")
    native = mesh.FemMesh
    if not native.EdgeCount or native.FaceCount or native.VolumeCount:
        raise ValueError(
            "Beam section output requires a pure 1D beam mesh; mixed dimensions are unsupported"
        )
    for element in native.Edges:
        ids = native.getElementNodes(element)
        if len(ids) != 3 or len(set(ids)) != 3:
            raise ValueError("Beam section output requires three distinct native B32R nodes")
        first, last, middle = (native.Nodes[node] for node in ids)
        length = (last - first).Length
        if (
            not all(math.isfinite(value) for point in (first, last, middle) for value in point)
            or not math.isfinite(length)
            or length <= 0
            or (middle - (first + last) * 0.5).Length > 1e-8 * length
        ):
            raise ValueError(
                "Beam section output currently requires straight quadratic beam segments"
            )
    end = solver.TimePeriod.Value
    if not math.isfinite(end) or end <= 0:
        raise ValueError("Beam section output requires a finite positive step period")


def begin_export(fea):
    invalidate(fea.analysis, "solver input rewrite attempted")
    if not enabled(fea.solver):
        return None
    preflight(fea.analysis, fea.solver, fea.mesh)
    return _model(fea.analysis, fea.mesh)


def _deck_sections(writer, literal):
    """Bind actual stock-written IDs, connectivity and section assignments."""
    nodes, elements, sets, sections = {}, {}, {}, []
    mode, options, rows = "", {}, []
    steps = 0

    def section():
        if mode == "*BEAM SECTION":
            if options.get("SECTION") != "RECT" or len(rows) != 2:
                raise ValueError(
                    "Native beam-end output currently qualifies rectangular sections only"
                )
            dimensions = [float(value) for value in rows[0]]
            axis = [float(value) for value in rows[1]]
            if (
                len(dimensions) != 2
                or len(axis) != 3
                or not all(math.isfinite(value) for value in dimensions + axis)
                or min(dimensions) <= 0
                or App.Vector(*axis).Length <= 0
            ):
                raise ValueError("Invalid native beam section dimensions or reference axis")
            sections.append(
                {
                    "elset": options["ELSET"],
                    "material": options["MATERIAL"],
                    "reference_n1": axis,
                    "dimensions_mm": dimensions,
                }
            )

    for raw in literal.splitlines():
        line = raw.strip()
        if not line or line.startswith("**"):
            continue
        if line.startswith("*"):
            section()
            tokens = [value.strip().upper() for value in line.split(",")]
            mode, options, rows = tokens[0], {}, []
            for token in tokens[1:]:
                key, separator, value = token.partition("=")
                options[key] = value if separator else True
            if mode == "*STEP":
                steps += 1
            if mode == "*ELEMENT" and options.get("TYPE") != "B32R":
                raise ValueError("Beam-end diagnostics require an exclusively B32R input deck")
            if mode == "*INCLUDE":
                raise ValueError("Beam-end diagnostics do not accept split input decks")
            continue
        values = [value.strip() for value in line.split(",") if value.strip()]
        if mode == "*NODE":
            node = int(values[0])
            if node in nodes or len(values) != 4:
                raise ValueError("Repeated or malformed native beam node")
            nodes[node] = [float(value) for value in values[1:]]
        elif mode == "*ELEMENT":
            element = int(values[0])
            if element in elements or len(values) != 4:
                raise ValueError("Repeated or malformed native beam element")
            elements[element] = list(map(int, values[1:]))
            if "ELSET" in options:
                sets.setdefault(options["ELSET"], []).append(element)
        elif mode == "*ELSET":
            target = sets.setdefault(options["ELSET"], [])
            if options.get("GENERATE"):
                if len(values) != 3:
                    raise ValueError("Malformed generated beam element set")
                start, end, stride = map(int, values)
                if stride <= 0 or end < start or len(range(start, end + 1, stride)) > len(elements):
                    raise ValueError("Unsupported generated beam element set")
                target.extend(range(start, end + 1, stride))
            else:
                target.extend(
                    int(value) if value.isdecimal() else value.upper() for value in values
                )
        elif mode == "*BEAM SECTION":
            rows.append(values)
    section()
    if steps != 1 or not elements or set(elements) != set(writer.mesh_object.FemMesh.Edges):
        raise ValueError(
            "Beam-end request needs exactly one static step and the original beam catalogue"
        )

    def expand(name, visiting=()):
        if name in visiting or name not in sets:
            raise ValueError("Unknown or recursive native beam element set")
        found = []
        for value in sets[name]:
            found.extend([value] if isinstance(value, int) else expand(value, (*visiting, name)))
        if len(found) != len(set(found)):
            raise ValueError("Repeated native beam section membership")
        return found

    names = {
        str(row["ccx_elset_name"]).upper(): row["beamsection_obj"].Name
        for row in writer.mat_geo_sets
        if "beamsection_obj" in row
    }
    catalogue = {}
    for record in sections:
        if record["elset"] not in names:
            raise ValueError("Beam section lacks its stock writer owner")
        for element in expand(record["elset"]):
            if element not in elements or element in catalogue:
                raise ValueError("Missing or multiply owned native beam element")
            first, middle, last = elements[element]
            original = list(writer.mesh_object.FemMesh.getElementNodes(element))
            if [first, last, middle] != original:
                raise ValueError("Native beam connectivity differs from the original mesh")
            for node in (first, middle, last):
                if (
                    node not in nodes
                    or node <= 0
                    or not all(math.isfinite(value) for value in nodes[node])
                    or (App.Vector(*nodes[node]) - writer.mesh_object.FemMesh.Nodes[node]).Length
                    > 1e-8 * max(1, App.Vector(*nodes[node]).Length)
                ):
                    raise ValueError("Native beam node identity or coordinates changed")
            catalogue[element] = {
                **record,
                "element": element,
                "nodes": [first, middle, last],
                "section": names[record["elset"]],
            }
    if set(catalogue) != set(elements):
        raise ValueError("Native beam sections do not cover the complete element catalogue")
    return [catalogue[element] for element in sorted(catalogue)]


def _retire_request(deck):
    request = _request_path(deck)
    paths = [
        path
        for path in (request, Path(str(request) + ".json"))
        if path.exists() or path.is_symlink()
    ]
    if not paths:
        return
    for path in paths:
        literal = _read(path)[0]
        valid = (
            _json(literal).get("schema") == SCHEMA
            if path.suffix == ".json"
            else literal.startswith((SCHEMA + "\n").encode())
        )
        if not valid:
            raise ValueError("Unrecognized beam request sibling; preserve and inspect it")
    recovery = Path(tempfile.mkdtemp(prefix=".previous-beam-request-", dir=request.parent))
    for path in paths:
        path.replace(recovery / path.name)


def prepare_request(writer):
    from femtools.contact_state import _write_generated

    if not enabled(writer.solver_obj):
        _retire_request(writer.file_name)
        return
    solver, analysis, mesh = writer.solver_obj, writer.analysis, writer.mesh_object
    preflight(analysis, solver, mesh)
    frozen = getattr(writer, "beam_section_export_digest", None)
    if frozen is None or _model(analysis, mesh) != frozen:
        raise ValueError("Beam inputs changed during export; rewrite the input")
    deck = Path(writer.file_name).resolve(strict=True)
    literal, deck_sha = _read(deck)
    text = literal.decode("utf-8")
    if "SECTION FORCES" not in text.upper():
        raise ValueError("The stock writer did not request native beam section forces")
    elements = _deck_sections(writer, text)
    binary = _binary(solver)
    binary_sha = _sha(binary)
    require_capability(binary)
    if _sha(binary) != binary_sha:
        raise ValueError("Beam diagnostic solver changed during capability query")
    token = uuid.uuid4().hex
    lines = [
        SCHEMA,
        "REQUEST " + token,
        f"END_TIME {solver.TimePeriod.Value:.17g}",
        "UNITS MM N NMM",
    ]
    lines.extend("ELEMENT {} {} {} {}".format(row["element"], *row["nodes"]) for row in elements)
    lines.append("END")
    request = _request_path(deck)
    _write_generated(request, "\n".join(lines) + "\n")
    metadata = {
        "schema": SCHEMA,
        "request": token,
        "request_path": str(request),
        "request_sha256": _sha(request),
        "deck": str(deck),
        "deck_sha256": deck_sha,
        "binary": binary,
        "binary_sha256": binary_sha,
        "model_hash": frozen,
        "end_time": solver.TimePeriod.Value,
        "elements": elements,
        "case": {"analysis": analysis.Name, "solver": solver.Name, "mesh": mesh.Name},
        "freecad_version": App.Version(),
    }
    if _model(analysis, mesh) != frozen or _sha(deck) != deck_sha:
        raise ValueError("Beam inputs changed while preparing the native request")
    _write_generated(
        Path(str(request) + ".json"), json.dumps(metadata, sort_keys=True, allow_nan=False)
    )


def _current(fea, metadata):
    if not enabled(fea.solver):
        return False
    preflight(fea.analysis, fea.solver, fea.mesh)
    deck = str(Path(fea.inp_file_name).resolve(strict=True))
    if (
        metadata["deck"] != deck
        or metadata["request_path"] != str(_request_path(deck))
        or metadata["case"]
        != {"analysis": fea.analysis.Name, "solver": fea.solver.Name, "mesh": fea.mesh.Name}
    ):
        return False
    if "run" in metadata:
        run = metadata["run"]
        if (
            not re.fullmatch(r"[0-9a-f]{32}", run["token"])
            or run["path"] != metadata["request_path"] + ".run-" + run["token"]
            or _sha(run["path"]) != run["sha256"]
        ):
            return False
    if "frd" in metadata:
        frd = metadata["frd"]
        if frd["path"] != str(Path(deck).with_suffix(".frd")) or _sha(frd["path"]) != frd["sha256"]:
            return False
    return (
        metadata["schema"] == SCHEMA
        and _model(fea.analysis, fea.mesh) == metadata["model_hash"]
        and _binary(fea.solver) == metadata["binary"]
        and _sha(metadata["binary"]) == metadata["binary_sha256"]
        and _sha(metadata["deck"]) == metadata["deck_sha256"]
        and _sha(metadata["request_path"]) == metadata["request_sha256"]
    )


def run_context(fea, binary, environment=None):
    from femtools.force_accounting import _prepare_movement_run

    invalidate(fea.analysis, "new solver run attempted")
    if not enabled(fea.solver):
        return None
    request = _request_path(fea.inp_file_name).resolve(strict=True)
    metadata = _json(_read(Path(str(request) + ".json"))[0])
    if str(Path(binary).resolve(strict=True)) != metadata["binary"] or not _current(fea, metadata):
        raise ValueError("Native beam request is stale; rewrite solver input")
    token = uuid.uuid4().hex
    literal = _read(request)[0].decode("utf-8")
    old = "REQUEST " + metadata["request"] + "\n"
    if literal.count(old) != 1:
        raise ValueError("Invalid native beam request token")
    child = Path(str(request) + ".run-" + token)
    output = Path(str(child) + ".out")
    if child.exists() or child.is_symlink() or output.exists() or output.is_symlink():
        raise ValueError("Native beam child output already exists")
    with child.open("x") as stream:
        stream.write(literal.replace(old, "REQUEST " + token + "\n"))
    metadata["run"] = {"token": token, "path": str(child), "sha256": _sha(child)}
    # Preserve a previous ordinary result recoverably, and refuse unsafe
    # output aliases before letting the native child open its FRD sibling.
    frd = _prepare_movement_run(fea.inp_file_name)
    env = dict(os.environ if environment is None else environment)
    env.pop(ENV, None)
    env[ENV] = str(child)
    key = (fea.analysis.Document.Name, fea.analysis.Name)
    _latest[key] = token
    return {
        "environment": env,
        "metadata": metadata,
        "output": str(output),
        "key": key,
        "finished": False,
        "frd": frd,
    }


def _validate_output(data, metadata):
    def finite(value):
        return type(value) in (int, float) and math.isfinite(value)

    def vector(value):
        return isinstance(value, list) and len(value) == 3 and all(map(finite, value))

    if (
        data.get("schema") != SCHEMA
        or data.get("request") != metadata["run"]["token"]
        or data.get("units") != UNITS
        or data.get("complete") is not True
        or data.get("position_frame") != "CURRENT_EXPANDED_SECTION"
        or data.get("basis_frame") != "NATIVE_CURRENT_FACE_BASIS"
        or data.get("sample_identity_scope") != "ELEMENT_END_BEFORE_NODE_AVERAGING"
        or data.get("moment_reference") != "NATIVE_SECTION_CENTROID"
        or data.get("force_action") != "OUTWARD_NATIVE_ELEMENT_END_FACE"
        or data.get("native_channels_method") != "PROJECTED_NATIVE_FORCE_AND_MOMENT_INCREMENT_SUM"
        or data.get("completion_requires_successful_child") is not True
    ):
        raise ValueError("Incomplete or mismatched native beam output")
    elements = {row["element"]: row for row in metadata["elements"]}
    expected = {
        (element, row["nodes"][end - 1], end) for element, row in elements.items() for end in (1, 3)
    }
    frames = data.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ValueError("Native beam output has no retained frames")
    identities = set()
    for frame in frames:
        values = [frame.get(name) for name in ("frame", "step", "increment")]
        if (
            not all(type(value) is int and value > 0 for value in values)
            or frame["step"] != 1
            or not finite(frame.get("time"))
            or frame["time"] <= 0
            or frame.get("complete") is not True
            or tuple(values) in identities
        ):
            raise ValueError("Invalid or repeated native beam frame identity")
        identities.add(tuple(values))
        seen = set()
        for row in frame.get("samples", []):
            key = tuple(row.get(name) for name in ("element", "node", "end"))
            if (
                not all(type(value) is int for value in key)
                or key not in expected
                or key in seen
                or not all(
                    vector(row.get(name)) for name in ("position", "force_global", "moment_global")
                )
            ):
                raise ValueError("Missing, repeated or nonfinite native beam-end sample")
            seen.add(key)
            basis = row.get("basis", {})
            if set(basis) != {"e1", "e2", "normal"} or not all(map(vector, basis.values())):
                raise ValueError("Native beam section axes are unavailable")
            axes = [App.Vector(*basis[name]) for name in ("e1", "e2", "normal")]
            if any(abs(axis.Length - 1) > 1e-6 for axis in axes) or any(
                abs(axes[i].dot(axes[j])) > 1e-6 for i, j in ((0, 1), (0, 2), (1, 2))
            ):
                raise ValueError("Native beam face projection axes are not orthonormal")
            channels = row.get("native_channels", {})
            if set(channels) != {
                "shear1",
                "shear2",
                "axial",
                "torque",
                "bend2",
                "bend1",
            } or not all(map(finite, channels.values())):
                raise ValueError("Native beam local force/moment channels are unavailable")
        if seen != expected:
            raise ValueError("Native beam frame does not cover every requested member end")
    if not math.isclose(frames[-1]["time"], metadata["end_time"], rel_tol=1e-10, abs_tol=1e-12):
        raise ValueError("Native beam output did not reach the requested final state")
    return data


def _make_result(fea):
    results = _results(fea.analysis)
    obj = (
        results[0]
        if results
        else fea.analysis.Document.addObject("App::FeaturePython", "BeamSectionForces")
    )
    if not results:
        BeamSectionForceResult(obj)
        obj.Label = "Native beam-end forces and moments"
        fea.analysis.addObject(obj)
    obj.Proxy._updating = True
    try:
        obj.Analysis, obj.Mesh, obj.Solver = fea.analysis, fea.mesh, fea.solver
    finally:
        obj.Proxy._updating = False
    return obj


def finish_run(fea, context, returncode, stdout):
    from femtools.force_accounting import _capture_movement

    if context is None:
        return
    metadata = context["metadata"]
    if context["finished"]:
        raise ValueError("Native beam completion was already consumed")
    context["finished"] = True
    if _latest.get(context["key"]) != metadata["run"]["token"]:
        return
    if returncode != 0:
        invalidate(fea.analysis, "native solver failed")
        return
    if not _current(fea, metadata):
        raise ValueError("Beam inputs changed while solving")
    frd = context["frd"]
    captured = _capture_movement(Path(frd["path"]))
    if "reason" in captured:
        raise ValueError("Native beam run has no owned fresh FRD: " + captured["reason"])
    metadata["frd"] = {"path": frd["path"], "sha256": captured["sha256"]}
    literal, output_sha = _read(context["output"])
    native = _validate_output(_json(literal), metadata)
    provenance = {
        **metadata,
        "output": context["output"],
        "output_sha256": output_sha,
        "stdout_sha256": hashlib.sha256(
            stdout.encode() if isinstance(stdout, str) else stdout
        ).hexdigest(),
        "completed_owned_run": True,
    }
    data = {**native, "provenance": provenance}
    encoded = json.dumps(data, sort_keys=True, allow_nan=False)
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    if not _current(fea, metadata) or _sha(context["output"]) != output_sha:
        raise ValueError("Beam output changed during publication")
    obj = _make_result(fea)
    obj.Proxy._updating = True
    try:
        obj.SectionData, obj.SectionHash = encoded, digest
        obj.CompletedRun = True
        _completed[context["key"]] = (metadata["run"]["token"], digest)
        obj.Status = "Current native member-end actions; not design acceptance"
    finally:
        obj.Proxy._updating = False
    return obj


def validate_frd(fea, filename):
    results = _results(fea.analysis)
    if len(results) != 1:
        raise ValueError("No unique completed native beam run owns the requested FRD")
    if (
        results[0].Analysis != fea.analysis
        or results[0].Mesh != fea.mesh
        or results[0].Solver != fea.solver
    ):
        raise ValueError("Native beam result belongs to another mesh or solver selection")
    data = results[0].Proxy.getSectionForces(results[0])
    source = data["provenance"]["frd"]
    if (
        str(Path(filename).resolve(strict=True)) != source["path"]
        or _sha(filename) != source["sha256"]
    ):
        raise ValueError("Displacement FRD is not the native beam run's exact fresh result")


class BeamSectionForceResult(BaseFemPythonObject):
    Type = "Fem::BeamSectionForceResult"

    def __init__(self, obj):
        self._updating = True
        super().__init__(obj)
        for kind, name, description in (
            ("App::PropertyLinkHidden", "Analysis", "Owning physical analysis"),
            ("App::PropertyLink", "Mesh", "Original beam mesh"),
            ("App::PropertyLink", "Solver", "Source solver and output request"),
            ("App::PropertyString", "Status", "Availability; never engineering acceptance"),
            ("App::PropertyString", "SectionData", "Literal native beam-end frames and provenance"),
            ("App::PropertyString", "SectionHash", "Identity of saved native output"),
            (
                "App::PropertyBool",
                "CompletedRun",
                "Owned completion; withdrawn on restore/new attempt",
            ),
        ):
            obj.addProperty(kind, name, "Beam Section Forces", description)
            obj.setPropertyStatus(name, "LockDynamic")
            obj.setEditorMode(name, 1)
            if name in {"Status", "SectionData", "SectionHash", "CompletedRun"}:
                obj.setPropertyStatus(name, "Output")
        obj.Status = "Unavailable: no completed native beam-end run"
        self._updating = False

    def _status(self, obj, status):
        self._updating = True
        try:
            obj.Status = status
        finally:
            self._updating = False

    def getSectionForces(self, obj, *, historical=False):
        try:
            if hashlib.sha256(obj.SectionData.encode()).hexdigest() != obj.SectionHash:
                raise ValueError("Saved native beam output changed")
            data = _json(obj.SectionData)
            metadata = data["provenance"]
            native = {key: value for key, value in data.items() if key != "provenance"}
            _validate_output(native, metadata)
            if historical:
                return data
            if not obj.Status.startswith("Current") or not obj.CompletedRun:
                raise ValueError("Native beam output is historical or withdrawn; rerun required")
            if not obj.Analysis or not obj.Mesh or not obj.Solver or obj not in obj.Analysis.Group:
                raise ValueError("Native beam source links are missing")
            if (
                any(
                    source.Document != obj.Document
                    for source in (obj.Analysis, obj.Mesh, obj.Solver)
                )
                or obj.Mesh not in obj.Analysis.Group
                or obj.Solver not in obj.Analysis.Group
            ):
                raise ValueError("Native beam source links belong to another analysis")
            key = (obj.Document.Name, obj.Analysis.Name)
            token = metadata["run"]["token"]
            if (
                _latest.get(key) != token
                or _completed.get(key) != (token, obj.SectionHash)
                or metadata.get("completed_owned_run") is not True
            ):
                raise ValueError(
                    "No current owned solver completion authenticates this beam output"
                )
            fea = SimpleNamespace(
                analysis=obj.Analysis,
                mesh=obj.Mesh,
                solver=obj.Solver,
                inp_file_name=metadata["deck"],
            )
            if (
                not _current(fea, metadata)
                or _sha(metadata["run"]["path"]) != metadata["run"]["sha256"]
                or metadata["output"] != metadata["run"]["path"] + ".out"
            ):
                raise ValueError("Beam request, physical model, mesh or solver changed")
            raw, digest = _read(metadata["output"])
            if (
                digest != metadata["output_sha256"]
                or _validate_output(_json(raw), metadata) != native
            ):
                raise ValueError("Saved beam frames differ from the owned native output")
            return data
        except Exception as error:
            if not historical:
                self._status(obj, "Stale: " + str(error))
            raise ValueError(str(error)) from error

    def execute(self, obj):
        pass

    def onChanged(self, obj, prop):
        if not getattr(self, "_updating", True) and prop in {
            "Analysis",
            "Mesh",
            "Solver",
            "SectionData",
            "SectionHash",
        }:
            self._status(obj, "Stale: native beam result inputs changed")

    def onDocumentRestored(self, obj):
        self._updating = True
        try:
            obj.CompletedRun = False
            obj.Status = "Historical native beam output; rerun required for Current data"
        finally:
            self._updating = False
        if obj.Analysis:
            key = (obj.Document.Name, obj.Analysis.Name)
            _latest[key] = None
            _completed.pop(key, None)
