# SPDX-License-Identifier: LGPL-2.1-or-later
"""Regression tests for exact reviewed-Qt catalogue selection."""

import copy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "package/qt-pdf/distribution.json"
HELPER = ROOT / "package/qt-pdf/verify_delivered_qt.py"
SPEC = importlib.util.spec_from_file_location("verify_delivered_qt", HELPER)
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


def catalogue():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def identity(entry):
    return {field: entry[field] for field in VERIFY.IDENTITY}


class ReviewedQtCatalogueTest(unittest.TestCase):
    def test_historical_builds_and_cocoa_build2_select_exactly(self):
        data = catalogue()
        for platform in VERIFY.PLATFORMS:
            entries = VERIFY.catalogue_entries(data, platform)
            name, entry = entries[0]
            selected_name, selected = VERIFY.select_catalogue_entry(
                entries, identity(entry)
            )
            self.assertEqual(selected_name, name)
            self.assertEqual(selected, entry)

        entries = VERIFY.catalogue_entries(data, "osx-arm64")
        self.assertEqual(
            [entry[0] for entry in entries], ["build1", "cocoa-accessibility-build2"]
        )
        variant, build2 = entries[1]
        selected_variant, selected = VERIFY.select_catalogue_entry(
            entries, identity(build2)
        )
        self.assertEqual(selected_variant, variant)
        self.assertEqual(selected, build2)

    def test_cocoa_build2_identity_is_not_a_generic_build_number_exception(self):
        entries = VERIFY.catalogue_entries(catalogue(), "osx-arm64")
        build2 = entries[1][1]
        for field, value in (
            ("build", "pl5321h12ef06d_3"),
            ("build_number", 3),
            ("sha256", "0" * 64),
        ):
            changed = identity(build2)
            changed[field] = value
            with self.assertRaises(ValueError):
                VERIFY.select_catalogue_entry(entries, changed)

        with self.assertRaises(ValueError):
            VERIFY.select_catalogue_entry(
                VERIFY.catalogue_entries(catalogue(), "osx-64"), identity(build2)
            )

        data = catalogue()
        data["conda"]["osx-arm64"]["build_number"] = 2
        with self.assertRaises(ValueError):
            VERIFY.catalogue_entries(data, "osx-arm64")

    def test_variant_cannot_change_a_file_owner_or_create_an_ambiguous_match(self):
        data = catalogue()
        variant = data["conda"]["osx-arm64"]["variants"]["cocoa-accessibility-build2"]
        path = next(iter(variant["verification_file_overrides"]))
        variant["verification_file_overrides"][path]["role"] = "qpa.mutated"
        with self.assertRaises(ValueError):
            VERIFY.catalogue_entries(data, "osx-arm64")

        data = catalogue()
        data["conda"]["osx-arm64"]["variants"]["cocoa-accessibility-build2"][
            "verification_sources"
        ]["original_paths_sha256"] = ("0" * 64)
        with self.assertRaises(ValueError):
            VERIFY.catalogue_entries(data, "osx-arm64")

        entries = VERIFY.catalogue_entries(catalogue(), "osx-arm64")
        duplicate = ("duplicate", copy.deepcopy(entries[1][1]))
        with self.assertRaises(ValueError):
            VERIFY.select_catalogue_entry(
                entries + [duplicate], identity(entries[1][1])
            )


if __name__ == "__main__":
    unittest.main()
