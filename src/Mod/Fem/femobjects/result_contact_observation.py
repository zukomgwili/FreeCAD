# SPDX-License-Identifier: LGPL-2.1-or-later
"""Editable contact-side observation result; never an engineering verdict."""

import json

from femobjects.base_fempythonobject import BaseFemPythonObject


class ContactObservationResult(BaseFemPythonObject):
    Type = "Fem::ContactSideObservation"
    _inputs = frozenset(("Analysis", "Mesh", "AccountingResult", "Contacts", "SlaveVertex"))

    def __init__(self, obj):
        self._updating = True
        super().__init__(obj)
        for kind, name, description in (
            # The containing analysis already links to this output. A native
            # dependency-hidden backlink avoids an analysis/result DAG cycle;
            # every qualified read validates the physical inputs separately.
            ("App::PropertyLinkHidden", "Analysis", "Analysis supplying the physical inputs"),
            ("App::PropertyLink", "Mesh", "Original mesh with native CAD ownership"),
            ("App::PropertyLink", "AccountingResult", "Native run with bound displacement output"),
            ("App::PropertyLinkList", "Contacts", "Independent contact-side references to observe"),
            (
                "App::PropertyIntegerConstraint",
                "SlaveVertex",
                "One-based existing slave-face vertex",
            ),
            (
                "App::PropertyString",
                "Status",
                "Availability and historical state; not design acceptance",
            ),
            (
                "App::PropertyString",
                "ObservationData",
                "Literal qualified side vectors and provenance",
            ),
            ("App::PropertyString", "ObservationHash", "Identity of the saved literal observation"),
        ):
            obj.addProperty(kind, name, "Contact Observation", description)
            obj.setPropertyStatus(name, "LockDynamic")
        obj.SlaveVertex = (1, 1, 1000000, 1)
        for name in ("Status", "ObservationData", "ObservationHash"):
            obj.setEditorMode(name, 1)
            obj.setPropertyStatus(name, "Output")
        obj.Status = "Unavailable: select analysis, mesh, native source and contacts"
        self._updating = False

    def refresh(self, obj):
        """Explicitly revalidate a saved source before exposing observations."""
        self._historical = False
        self._updating = True
        try:
            if not (obj.Analysis and obj.Mesh and obj.AccountingResult and obj.Contacts):
                obj.Status = "Unavailable: select analysis, mesh, native source and contacts"
                return
            metadata = json.loads(obj.AccountingResult.AccountingData or "{}")
            if metadata.get("movement_source", {}).get("status") != "BOUND":
                obj.Status = "Unavailable: no bound native movement source; rerun native accounting"
                return
            from femresult.contact_observation import data_digest, observe

            report = observe(obj)
            obj.ObservationData = json.dumps(report, sort_keys=True, allow_nan=False)
            obj.ObservationHash = data_digest(obj.ObservationData)
            if report["status"] == "AVAILABLE":
                obj.Status = (
                    "Available at last refresh; revalidate before use; not design acceptance"
                )
            else:
                obj.Status = (
                    "Unavailable: one or more requested native side samples are unavailable"
                )
        except Exception as error:
            # Native OCC/VTK adapters can raise other exception classes. The
            # public action must never retain an Available label after failure.
            obj.Status = "Unavailable: " + str(error)
        finally:
            self._updating = False

    def getObservations(self, obj):
        """Return qualified values, never interpret absent samples as zeros."""
        if not obj.Status.startswith("Available"):
            raise ValueError(obj.Status)
        from femresult.contact_observation import data_digest, validate_observation

        try:
            if data_digest(obj.ObservationData) != obj.ObservationHash:
                raise ValueError("Saved observation data changed; refresh required")
            report = json.loads(obj.ObservationData)
            validate_observation(obj, report)
            return report
        except Exception as error:
            self._updating = True
            try:
                obj.Status = "Unavailable: " + str(error)
            finally:
                self._updating = False
            raise ValueError(obj.Status) from error

    def execute(self, obj):
        # Recompute must not read a new solver source or qualify saved history.
        # The user explicitly refreshes this observation when ready.
        pass

    def onChanged(self, obj, prop):
        if not getattr(self, "_updating", True) and prop in self._inputs | {
            "ObservationData",
            "ObservationHash",
        }:
            self._updating = True
            try:
                obj.Status = "Stale after observation input change; refresh required"
            finally:
                self._updating = False

    def onDocumentRestored(self, obj):
        self._updating = True
        self._historical = True
        obj.Status = "Historical after restore; refresh required"
        self._updating = False
