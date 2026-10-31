# SPDX-License-Identifier: LGPL-2.1-or-later
"""One owned completion for coupled beam actions and native contact samples.

This module binds two literal observations. It neither recovers forces nor
changes the solver's fields, mechanics or contact state.
"""

import hashlib
import json
from dataclasses import dataclass

import FreeCAD as App

SCHEMA = "FREECAD_BEAM_CONTACT_RUN_V1"
BEAM_SCHEMA = "CCX_BEAM_SECTION_V4"
_pairs = {}
_withdrawing = False


@dataclass(frozen=True)
class _Pair:
    beam: object
    contact: object
    beam_hash: str
    contact_hash: str
    joint: dict
    analysis: object
    mesh: object
    solver: object


def _key(analysis):
    return analysis.Document.Name, analysis.Name


def _encoded(value):
    return json.dumps(value, sort_keys=True, allow_nan=False)


def _hash(literal):
    return hashlib.sha256(literal.encode()).hexdigest()


def _withdraw(key, objects, reason):
    """Withdraw the actual cached objects, including detached companions."""
    global _withdrawing
    if _withdrawing:
        return
    from femtools import beam_section_forces, contact_state

    _withdrawing = True
    try:
        _pairs.pop(key, None)
        beam_section_forces._latest[key] = None
        beam_section_forces._completed.pop(key, None)
        contact_state._latest_attempt[key] = None
        for obj in objects:
            try:
                previous = obj.Proxy._updating
                obj.Proxy._updating = True
                try:
                    obj.CompletedRun = False
                    obj.Status = "Stale: " + reason
                finally:
                    obj.Proxy._updating = previous
            except (ReferenceError, RuntimeError):
                # A destroyed C++ object cannot retain observable availability.
                continue
    finally:
        _withdrawing = False


def invalidate(analysis, reason, *, extra=()):
    """Withdraw a run without discarding either literal saved observation."""
    from femtools import beam_section_forces, contact_state

    key = _key(analysis)
    cached = _pairs.get(key)
    objects = [*beam_section_forces._results(analysis), *contact_state._results(analysis), *extra]
    if cached is not None:
        objects.extend((cached.beam, cached.contact))
    _withdraw(key, objects, reason)


def withdraw_result(result, reason):
    """Find a pair even after a result's Analysis link or membership changed."""
    for key, cached in tuple(_pairs.items()):
        if result in (cached.beam, cached.contact):
            _withdraw(key, (cached.beam, cached.contact), reason)
            return True
    return False


def begin_export(fea):
    """Withdraw both before either physical-input capture is allowed to fail."""
    if (
        fea.analysis is not None
        and getattr(fea.solver, "BeamSectionForces", False)
        and getattr(fea.solver, "NativeContactOutputs", ())
    ):
        invalidate(fea.analysis, "new paired beam/contact export attempted")


def begin_run(fea):
    """Retire old companions before either new child token can be allocated.

    A repeated run may reuse a current export. Reads of the withdrawn old
    observations must not find a cached pair that can cancel the new child.
    """
    if fea.analysis is not None and (
        _key(fea.analysis) in _pairs
        or getattr(fea.solver, "BeamSectionForces", False)
        and getattr(fea.solver, "NativeContactOutputs", ())
    ):
        invalidate(fea.analysis, "new paired beam/contact run attempted")


def _frame_keys(data):
    return {(row["step"], row["increment"], row["time"]) for row in data["frames"]}


def _prevalidate(fea, beam, contact):
    from femtools import beam_section_forces as bs
    from femtools import contact_state as cs

    bm, cm = beam["metadata"], contact["metadata"]
    if not bs._current(fea, bm) or not cs._current(fea, cm):
        raise ValueError("Coupled beam/contact inputs changed before completion")
    case = {"analysis": fea.analysis.Name, "solver": fea.solver.Name, "mesh": fea.mesh.Name}
    if (
        bm["case"] != case
        or {key: cm[key] for key in case} != case
        or any(bm[key] != cm[key] for key in ("deck", "deck_sha256", "binary", "binary_sha256"))
        or bm["model_hash"] != cm["model_digest"]
        or bm["end_time"] != cm["end_time"]
        or bm["run"].get("contact_binding") != cm["run"]
    ):
        raise ValueError("Coupled observations do not belong to one owned solver child")
    beam_bytes, beam_hash = bs._read(beam["output"])
    contact_bytes, contact_hash = cs._capture(contact["output"])
    native_beam = bs._validate_output(bs._json(beam_bytes), bm)
    native_contact = cs._validate_output(cs._json(contact_bytes), cm)
    if (
        native_beam.get("contact_request") != cm["run"]["token"]
        or _frame_keys(native_beam) != _frame_keys(native_contact)
        or len(native_beam["frames"]) != 1
        or len(native_contact["frames"]) != 1
    ):
        raise ValueError("Native beam/contact completion frames or child identities differ")
    # These are native step/increment/time identities. The beam STRESS dataset
    # counter and the contact integration-point labels are separate identities.
    return beam_hash, contact_hash


def _stamp(obj, data, joint, attribute, hash_attribute):
    data["provenance"]["joint"] = joint
    literal = _encoded(data)
    obj.Proxy._updating = True
    try:
        setattr(obj, attribute, literal)
        setattr(obj, hash_attribute, _hash(literal))
    finally:
        obj.Proxy._updating = False


def finish_run(fea, beam, contact, returncode, stdout):
    """Handle V4 jointly; return False for the unchanged independent workflows."""
    from femtools import beam_section_forces as bs
    from femtools import contact_state as cs

    if beam is None or beam["metadata"]["schema"] != BEAM_SCHEMA:
        return False
    if contact is None:
        invalidate(fea.analysis, "coupled native contact completion is missing")
        raise ValueError("Coupled beam output requires its owned contact completion")
    key = _key(fea.analysis)
    if (
        bs._latest.get(key) != beam["metadata"]["run"]["token"]
        or cs._latest_attempt.get(key) != contact["metadata"]["run"]["token"]
    ):
        beam["finished"] = contact["finished"] = True
        return True
    _pairs.pop(key, None)
    published = []
    try:
        if returncode != 0:
            cs.finish_run(fea, contact, returncode, stdout)
            bs.finish_run(fea, beam, returncode, stdout)
            return True
        if beam["finished"] or contact["finished"]:
            raise ValueError("Coupled native completion was already consumed")
        hashes = _prevalidate(fea, beam, contact)
        if len(bs._results(fea.analysis)) > 1 or len(cs._results(fea.analysis)) > 1:
            raise ValueError("Coupled output requires unique beam and contact results")
        contact_result = cs.finish_run(fea, contact, returncode, stdout)
        if contact_result is not None:
            published.append(contact_result)
        beam_result = bs.finish_run(fea, beam, returncode, stdout)
        if beam_result is not None:
            published.append(beam_result)
        if beam_result is None or contact_result is None:
            raise ValueError("A coupled native completion was withdrawn during publication")
        bd, cd = bs._json(beam_result.SectionData), cs._json(contact_result.ContactData)
        bp, cp = bd["provenance"], cd["provenance"]
        if (bp["output_sha256"], cp["output_sha256"]) != hashes:
            raise ValueError("Coupled native outputs changed during publication")
        joint = {
            "schema": SCHEMA,
            "case": bp["case"],
            "model_digest": bp["model_hash"],
            "deck": {"path": bp["deck"], "sha256": bp["deck_sha256"]},
            "binary": {"path": bp["binary"], "sha256": bp["binary_sha256"]},
            "frd": bp["frd"],
            "frames": [list(value) for value in sorted(_frame_keys(bd))],
            "stdout_sha256": bp["stdout_sha256"],
            "beam": {**bp["run"], "output": bp["output"], "output_sha256": hashes[0]},
            "contact": {**cp["run"], "output": cp["output"], "output_sha256": hashes[1]},
        }
        if cp["stdout_sha256"] != joint["stdout_sha256"]:
            raise ValueError("Coupled observations have different solver stdout identities")
        _stamp(beam_result, bd, joint, "SectionData", "SectionHash")
        _stamp(contact_result, cd, joint, "ContactData", "ContactHash")
        bs._completed[key] = (bp["run"]["token"], beam_result.SectionHash)
        _pairs[key] = _Pair(
            beam_result,
            contact_result,
            beam_result.SectionHash,
            contact_result.ContactHash,
            joint,
            fea.analysis,
            fea.mesh,
            fea.solver,
        )
        require_current(beam_result, bs._json(beam_result.SectionData))
        return True
    except Exception:
        invalidate(fea.analysis, "paired native beam/contact completion failed", extra=published)
        raise


def require_current(result, data):
    """Authenticate both companions without recursively calling their getters."""
    from femtools import beam_section_forces as bs
    from femtools import contact_state as cs

    analysis = result.Analysis
    try:
        record = _pairs.get(_key(analysis))
        if record is None:
            raise ValueError("No current owned completion authenticates the paired observations")
        beam, contact, joint = record.beam, record.contact, record.joint
        if (
            result not in (beam, contact)
            or bs._results(analysis) != [beam]
            or cs._results(analysis) != [contact]
            or analysis != record.analysis
            or beam.Analysis != record.analysis
            or contact.Analysis != record.analysis
            or beam.Mesh != record.mesh
            or contact.Mesh != record.mesh
            or beam.Solver != record.solver
            or contact.Solver != record.solver
            or not all(
                obj.CompletedRun and obj.Status.startswith("Current") for obj in (beam, contact)
            )
            or beam.SectionHash != record.beam_hash
            or contact.ContactHash != record.contact_hash
            or _hash(beam.SectionData) != record.beam_hash
            or _hash(contact.ContactData) != record.contact_hash
            or bs._latest.get(_key(record.analysis)) != joint["beam"]["token"]
            or data["provenance"].get("joint") != joint
            or bs._json(beam.SectionData)["provenance"].get("joint") != joint
            or cs._json(contact.ContactData)["provenance"].get("joint") != joint
        ):
            raise ValueError("Paired beam/contact results or source links changed")
        for channel in ("beam", "contact"):
            source = joint[channel]
            if (
                bs._sha(source["path"]) != source["sha256"]
                or bs._sha(source["output"]) != source["output_sha256"]
            ):
                raise ValueError("A paired native request or output changed")
        for channel in ("deck", "binary", "frd"):
            source = joint[channel]
            if bs._sha(source["path"]) != source["sha256"]:
                raise ValueError("Paired native input, executable or displacement source changed")
    except Exception as error:
        withdraw_result(result, str(error))
        raise ValueError(str(error)) from error


class _Observer:
    def slotChangedObject(self, obj, prop):
        if not _pairs or _withdrawing or getattr(getattr(obj, "Proxy", None), "_updating", False):
            return
        from femtools import contact_state as cs
        from femtools.force_accounting import _is_result

        for key, record in tuple(_pairs.items()):
            beam, contact = record.beam, record.contact
            if obj.Document != record.analysis.Document:
                continue
            try:
                if (
                    beam.Analysis != record.analysis
                    or contact.Analysis != record.analysis
                    or beam not in record.analysis.Group
                    or contact not in record.analysis.Group
                    or beam.Mesh != record.mesh
                    or contact.Mesh != record.mesh
                    or beam.Solver != record.solver
                    or contact.Solver != record.solver
                ):
                    _withdraw(key, (beam, contact), "paired source links or membership changed")
                elif obj in (beam, contact) and prop in {
                    "Analysis",
                    "Mesh",
                    "Solver",
                    "SectionData",
                    "SectionHash",
                    "ContactData",
                    "ContactHash",
                    "CompletedRun",
                    "Status",
                }:
                    _withdraw(key, (beam, contact), "a paired result was changed")
                elif (
                    not _is_result(obj)
                    and cs._model(record.analysis, record.mesh) != record.joint["model_digest"]
                ):
                    _withdraw(key, (beam, contact), "paired physical model or request changed")
            except Exception:
                _withdraw(key, (beam, contact), "paired physical sources cannot be validated")

    def slotDeletedObject(self, obj):
        for key, record in tuple(_pairs.items()):
            if obj in (record.beam, record.contact, record.analysis, record.mesh, record.solver):
                _withdraw(key, (record.beam, record.contact), "a paired native source was deleted")

    def slotDeletedDocument(self, doc):
        for key in tuple(_pairs):
            if key[0] == doc.Name:
                _pairs.pop(key, None)


_observer = _Observer()
App.addDocumentObserver(_observer)
