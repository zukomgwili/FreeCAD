# SPDX-License-Identifier: LGPL-2.1-or-later
"""Contact wire admission, independent of native mechanics qualification.

These literal protocol fixtures exercise the production importer. They neither
simulate a contact solve nor establish the physical accuracy of their samples.
Actual regenerated native catalogues are checked by staged self-weight tests.
"""

import copy
import math
import unittest

from femtools import contact_state


class TestContactStateCatalogue(unittest.TestCase):
    def fixture(self, *, frame_local=True, changing=True):
        token = "1" * 32
        metadata = {
            "run": {"token": token},
            "end_time": 1.0,
            "contacts": [
                {"contact": "Interface", "slave_faces": [[10, 1]], "master_faces": [[20, 1]]}
            ],
        }

        def frame(increment, time, labels):
            faces = [
                {
                    "contact": "Interface",
                    "native_pair": 1,
                    "slave_element": 10,
                    "slave_face": 1,
                    "expected_points": len(labels),
                }
            ]
            inventory, samples = [], []
            for local, native in enumerate(labels, 1):
                identity = {
                    "contact": "Interface",
                    "native_pair": 1,
                    "slave_element": 10,
                    "slave_face": 1,
                    "native_point": native,
                    "local_point": local,
                }
                inventory.append(identity)
                samples.append(
                    {
                        **identity,
                        "availability": "UNPAIRED",
                        "state": "UNAVAILABLE",
                        "evaluation": "UNAVAILABLE",
                        "engagement": "UNAVAILABLE",
                        "slave_position": [0, 0, 0],
                        "slave_parameters": [0.2, 0.2],
                        "weight": 1.0,
                        **{
                            name: None
                            for name in (
                                "master_element",
                                "master_face",
                                "master_position",
                                "master_parameters",
                                "normal",
                                "tangent1",
                                "tangent2",
                                "clearance",
                                "area",
                                "pressure",
                                "tangential_displacement",
                                "shear",
                                "plastic_slip_increment",
                                "plastic_slip_vector",
                            )
                        },
                    }
                )
            return {
                "step": 1,
                "increment": increment,
                "time": time,
                "success": True,
                "complete": time == 1.0,
                "face_inventory": faces,
                "sample_inventory": inventory,
                "samples": samples,
            }

        frames = [frame(1, 0.5, (1, 2)), frame(2, 1.0, (5, 6, 7) if changing else (1, 2))]
        data = {
            "schema": contact_state.SCHEMA,
            "request": token,
            "complete": True,
            "units": {"length": "mm", "force": "N", "stress": "MPa"},
            "position_frame": "CURRENT_WITH_NATIVE_CLEARANCE_ADJUSTMENT",
            "basis_frame": "NATIVE_MASTER_NORMAL",
            "sample_identity_scope": "FRAME_LOCAL_NATIVE_CATALOGUE",
            "frames": frames,
            **{
                name: copy.deepcopy(frames[-1][name])
                for name in ("face_inventory", "sample_inventory")
            },
        }
        if frame_local:
            data["inventory_scope"] = "PER_RETAINED_FRAME"
        else:
            for item in frames:
                item.pop("face_inventory")
                item.pop("sample_inventory")
        return data, metadata

    def test_each_native_frame_uses_its_own_complete_catalogue(self):
        data, metadata = self.fixture()
        self.assertEqual(contact_state._validate_output(data, metadata), data)
        self.assertEqual([len(frame["samples"]) for frame in data["frames"]], [2, 3])

    def test_reused_raw_point_labels_do_not_establish_cross_frame_identity(self):
        data, metadata = self.fixture()
        final = data["frames"][-1]
        final["sample_inventory"][0]["native_point"] = 1
        final["samples"][0]["native_point"] = 1
        final["samples"][0]["slave_parameters"] = [0.3, 0.4]
        data["sample_inventory"] = copy.deepcopy(final["sample_inventory"])
        self.assertEqual(contact_state._validate_output(data, metadata), data)

    def test_legacy_v1_keeps_its_shared_catalogue_invariant(self):
        data, metadata = self.fixture(frame_local=False, changing=False)
        self.assertEqual(contact_state._validate_output(data, metadata), data)
        changed, metadata = self.fixture(frame_local=False, changing=True)
        with self.assertRaises(ValueError):
            contact_state._validate_output(changed, metadata)

    def test_marker_partial_catalogues_and_final_alias_changes_are_refused(self):
        for mutation in (
            "missing marker",
            "unknown marker",
            "null marker",
            "missing frame faces",
            "missing frame samples",
            "missing top faces",
            "wrong top samples",
        ):
            with self.subTest(mutation=mutation):
                data, metadata = self.fixture()
                if mutation == "missing marker":
                    data.pop("inventory_scope")
                elif mutation == "unknown marker":
                    data["inventory_scope"] = "SHARED_OR_GUESSED"
                elif mutation == "null marker":
                    data["inventory_scope"] = None
                elif mutation == "missing frame faces":
                    data["frames"][0].pop("face_inventory")
                elif mutation == "missing frame samples":
                    data["frames"][0].pop("sample_inventory")
                elif mutation == "missing top faces":
                    data.pop("face_inventory")
                else:
                    data["sample_inventory"].pop()
                with self.assertRaises(ValueError):
                    contact_state._validate_output(data, metadata)

    def test_each_frame_refuses_omitted_duplicate_or_wrong_owned_samples(self):
        for mutation in (
            "missing sample",
            "duplicate sample",
            "missing inventory sample",
            "wrong inventory sample",
            "local gap",
            "wrong face count",
            "wrong slave owner",
            "changed native pair",
        ):
            with self.subTest(mutation=mutation):
                data, metadata = self.fixture()
                frame = data["frames"][0]
                if mutation == "missing sample":
                    frame["samples"].pop()
                elif mutation == "duplicate sample":
                    frame["samples"].append(copy.deepcopy(frame["samples"][0]))
                elif mutation == "missing inventory sample":
                    frame["sample_inventory"].pop()
                elif mutation == "wrong inventory sample":
                    frame["sample_inventory"][0]["native_point"] = 99
                elif mutation == "local gap":
                    frame["sample_inventory"][1]["local_point"] = 3
                    frame["samples"][1]["local_point"] = 3
                elif mutation == "wrong face count":
                    frame["face_inventory"][0]["expected_points"] = 3
                else:
                    field = "native_pair" if mutation == "changed native pair" else "slave_element"
                    for name in ("face_inventory", "sample_inventory", "samples"):
                        for row in frame[name]:
                            row[field] = 2 if field == "native_pair" else 99
                with self.assertRaises(ValueError):
                    contact_state._validate_output(data, metadata)

    def test_empty_native_face_catalogue_does_not_invent_sample_state(self):
        data, metadata = self.fixture()
        for frame in data["frames"]:
            frame["face_inventory"][0]["expected_points"] = 0
            frame["sample_inventory"] = []
            frame["samples"] = []
        data["face_inventory"] = copy.deepcopy(data["frames"][-1]["face_inventory"])
        data["sample_inventory"] = []
        self.assertEqual(contact_state._validate_output(data, metadata), data)

    def test_native_endpoint_roundoff_is_bounded_without_rewriting_actual_time(self):
        for direction in (-math.inf, math.inf):
            actual = 1.0
            for neighbours in range(1, 6):
                actual = math.nextafter(actual, direction)
                with self.subTest(direction=direction, neighbours=neighbours):
                    data, metadata = self.fixture()
                    data["frames"][-1]["time"] = actual
                    if neighbours <= 4:
                        validated = contact_state._validate_output(data, metadata)
                        self.assertEqual(validated["frames"][-1]["time"], actual)
                        self.assertNotEqual(actual, metadata["end_time"])
                    else:
                        with self.assertRaises(ValueError):
                            contact_state._validate_output(data, metadata)

    def test_near_end_time_cannot_promote_an_incomplete_native_output(self):
        for mutation in ("incomplete frame", "incomplete output", "earlier frame"):
            with self.subTest(mutation=mutation):
                data, metadata = self.fixture()
                frame = data["frames"][-1]
                frame["time"] = math.nextafter(1.0, -math.inf)
                if mutation == "incomplete frame":
                    frame["complete"] = False
                elif mutation == "incomplete output":
                    data["complete"] = False
                else:
                    frame["time"] = 1.0 - 5e-13
                    frame["complete"] = False
                with self.assertRaises(ValueError):
                    contact_state._validate_output(data, metadata)
