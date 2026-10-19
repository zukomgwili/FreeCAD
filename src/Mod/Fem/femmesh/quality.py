# SPDX-License-Identifier: LGPL-2.1-or-later

"""Diagnostic readiness, not a numerical mesh-quality or engineering oracle.

Only native diagnostic failures establish Known failed. Silence, successful mesh
import and successful input writing establish no positive Jacobian criterion.
Evidence is invalidated on cold restore: native mesh persistence can renumber
elements, so old diagnostic IDs must not highlight unrelated current elements.
"""

import hashlib
import json
import os
import re

import FreeCAD

from femtools.native_properties import property_value

from . import meshtools


class NativeDiagnostics:
    """Observe diagnostic lines without consuming a QProcess log channel."""

    def __init__(self, process):
        from PySide.QtCore import QProcess

        self.process = process
        self.channels = (QProcess.StandardOutput, QProcess.StandardError)
        self.reset()
        process.readyReadStandardOutput.connect(lambda: self.observe(self.channels[0]))
        process.readyReadStandardError.connect(lambda: self.observe(self.channels[1]))

    def reset(self):
        self.lines = set()
        self.tails = {}
        self.buffers = {}

    def observe(self, channel):
        previous = self.process.readChannel()
        self.process.setReadChannel(channel)
        data = bytes(self.process.peek(self.process.bytesAvailable()))
        self.process.setReadChannel(previous)
        previous_data = self.buffers.get(channel, b"")
        self.buffers[channel] = data
        # Without a GUI consumer QProcess retains its entire buffer. Parse only
        # newly appended bytes; after a consumer drains it, parse the new chunk.
        fresh = data[len(previous_data) :] if data.startswith(previous_data) else data
        text = fresh.decode("utf-8", "replace")
        text = self.tails.get(channel, "") + text
        lines = text.splitlines(keepends=True)
        self.tails[channel] = ""
        if lines and not lines[-1].endswith(("\n", "\r")):
            self.tails[channel] = lines.pop()
        for line in lines:
            if re.search(
                r"jacobian|ScaledJac|elements? with jac\.|determinant in element|Version",
                line,
                re.IGNORECASE,
            ):
                self.lines.add(line.rstrip())

    def text(self):
        for channel in self.channels:
            self.observe(channel)
        return "\n".join(sorted(self.lines | set(self.tails.values()))).strip()


def initialize(mesh):
    for name, description in (
        (
            "QualityState",
            "Unchecked or Known failed native diagnostic readiness; not design acceptance",
        ),
        ("QualitySummary", "Scope and limitations of the native diagnostic readiness"),
        ("QualityEvidence", "JSON native diagnostic provenance; historical after invalidation"),
    ):
        if name not in mesh.PropertiesList:
            mesh.addProperty("App::PropertyString", name, "Mesh Quality", description)
            mesh.setPropertyStatus(name, "LockDynamic")
        mesh.setEditorMode(name, 1)
    if not mesh.QualityState:
        invalidate(mesh, "No native quality criterion has been established.")


def invalidate(mesh, reason):
    if "QualityState" in mesh.PropertiesList:
        mesh.QualityState = "Unchecked"
        mesh.QualitySummary = reason


def input_fingerprint(mesh):
    """Bind diagnostics to exact current native connectivity, geometry and controls."""
    digest = hashlib.sha256()
    native = mesh.FemMesh
    for node, point in sorted(native.Nodes.items()):
        digest.update(repr((node, tuple(point))).encode())
    for element in native.getIdByElementType("All"):
        digest.update(repr((element, tuple(native.getElementNodes(element)))).encode())
    controls = {}
    seen = set()

    def control(value):
        if hasattr(value, "Document") and hasattr(value, "PropertiesList"):
            key = (value.Document.Name, value.Name)
            if key in seen:
                return key
            seen.add(key)
            return [
                key,
                {
                    name: control(value.getPropertyByName(name))
                    for name in sorted(value.PropertiesList)
                    if name not in ("Shape", "Proxy", "ExpressionEngine")
                },
            ]
        if isinstance(value, (list, tuple)):
            return [control(item) for item in value]
        return property_value(value)

    for name in sorted(mesh.PropertiesList):
        if mesh.getGroupOfProperty(name) in ("Mesh Parameters", "Mesh Provenance", "FEM Mesh"):
            if name not in ("FemMesh", "WorkingDirectory"):
                controls[name] = control(mesh.getPropertyByName(name))
    digest.update(json.dumps(controls, sort_keys=True).encode())
    if getattr(mesh, "Shape", None):
        digest.update(meshtools.get_mesh_geometry_signature(mesh.Shape).encode())
    return digest.hexdigest()


def readiness(mesh):
    """Return current structured state; invalidate stale diagnostic identities."""
    initialize(mesh)
    evidence = json.loads(mesh.QualityEvidence or "{}")
    if mesh.QualityState == "Known failed":
        if evidence.get("fingerprint") != input_fingerprint(mesh):
            invalidate(
                mesh, "Mesh, geometry or controls changed; previous diagnostics are historical."
            )
    return {"state": mesh.QualityState, "summary": mesh.QualitySummary, "evidence": evidence}


def record(
    mesh,
    source,
    text,
    *,
    exit_code=None,
    command="",
    scope="current mesh",
    binary="",
    input_signature=None,
):
    """Publish native failure evidence without changing or consuming its raw log.

    CalculiX IDs use current FreeCAD input-deck labels. Gmsh IDs, if printed,
    belong to its generation attempt and are not imported FreeCAD element IDs.
    Successful native runs remain unchecked, not implicitly qualified.
    """
    initialize(mesh)
    text = "\n".join(
        line
        for line in text.splitlines()
        if re.search(
            r"jacobian|ScaledJac|elements? with jac\.|determinant in element|Version",
            line,
            re.IGNORECASE,
        )
    )
    ids = []
    failed = False
    if source == "CalculiX":
        failed = "*ERROR in e_c3d: nonpositive jacobian" in text
        if failed:
            ids = sorted(
                {int(value) for value in re.findall(r"determinant in element\s+(\d+)", text)}
            )
    elif source == "Gmsh":
        failed = any(
            int(value) > 0
            for value in re.findall(r"(\d+)\s+elements? with jac\.\s*<\s*0", text, re.IGNORECASE)
        )
        failed = failed or bool(
            re.search(
                r"(?:Error[^\n]*(?:ScaledJac|Jacobian)|negative Jacobian)", text, re.IGNORECASE
            )
        )
    else:
        raise ValueError("Unknown native mesh-quality diagnostic source")
    current_signature = input_fingerprint(mesh)
    binary_sha256 = None
    if binary and os.path.isfile(binary):
        with open(binary, "rb") as stream:
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
            binary_sha256 = digest.hexdigest()
    evidence = {
        "version": 1,
        "source": source,
        "scope": scope,
        "command": command,
        "exit_code": exit_code,
        "criterion": "native nonpositive-Jacobian diagnostics",
        "element_ids": ids,
        "element_id_namespace": "FreeCAD input deck" if ids else source,
        "diagnostic_text": text,
        "diagnostic_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "fingerprint": input_signature or current_signature,
        "binary": binary,
        "binary_sha256": binary_sha256,
        "freecad_version": list(FreeCAD.Version()),
    }
    # Do not let a later silent run erase a known failure for an unchanged mesh.
    current = readiness(mesh)
    if input_signature is not None and input_signature != current_signature:
        mesh.QualityEvidence = json.dumps(evidence, sort_keys=True)
        invalidate(mesh, "Input changed during native check; diagnostics are historical.")
        return readiness(mesh)
    if not failed and current["state"] == "Known failed":
        return current
    mesh.QualityEvidence = json.dumps(evidence, sort_keys=True)
    mesh.QualityState = "Known failed" if failed else "Unchecked"
    mesh.QualitySummary = (
        f"{source}: nonpositive-Jacobian failure ({scope}); inspect native diagnostics."
        if failed
        else f"{source}: no positive quality criterion established ({scope})."
    )
    return readiness(mesh)
