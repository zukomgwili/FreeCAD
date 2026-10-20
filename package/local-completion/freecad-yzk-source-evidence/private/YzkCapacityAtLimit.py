# SPDX-License-Identifier: LGPL-2.1-or-later
"""Same independently frozen graph/oracles at its exact resource budget.

Only the external process resource policy changes; geometry, loads, physical
supports, cut ownership, sampling and acceptance references remain untouched.
"""
import json
import os
from pathlib import Path
from unittest.mock import patch

import YzkCoupledWitness as witness
from YzkCoupledFixture import write_json


class CapacityAtLimitWitness(witness.CoupledFiniteFaceWitness):
    def test_independent_head_ports_keep_the_complete_coupled_physical_graph(self):
        self.assertEqual(os.environ["YZK_CASE"], "capacity")
        with patch.dict(os.environ, {"CCX_FORCE_ACCOUNTING_MAX_DECLARATIONS": "2113"}):
            super().test_independent_head_ports_keep_the_complete_coupled_physical_graph()
        output = Path(os.environ["YZK_OUTPUT"]) / "witness"
        data = json.loads((output / "native-accounting-data.json").read_text())
        required = {
            "supports": 1, "bodies": 264, "ports": 264, "angles": 792, "springs": 792,
        }
        self.assertEqual(data["capacity"]["required"], required)
        self.assertEqual(data["capacity"]["total"], 2113)
        self.assertEqual(data["capacity"]["supported"]["total_records"], 2113)
        self.assertEqual(data["capacity_applied"], {
            "budget": 2113, "counts": required, "total": 2113,
        })
        write_json(output / "exact-budget-proof.json", {
            "passed": True, "budget": 2113, "required": required,
            "actual_owned_child_receipt": data["capacity_applied"],
            "same_frozen_geometry_loads_supports_and_oracles": True,
            "engineering_or_BIM_accepted": False,
        })
