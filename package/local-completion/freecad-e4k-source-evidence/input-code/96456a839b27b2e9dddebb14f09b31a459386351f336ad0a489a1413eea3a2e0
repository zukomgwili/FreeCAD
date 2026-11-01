# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2025 Jakub Michalski <jakub.j.michalski[at]gmail.com>         *
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

__title__ = "FreeCAD FEM calculix amplitude"
__author__ = "Jakub Michalski"
__url__ = "https://www.freecad.org"

import math
import re

_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?\Z")


def _validate_amplitude(obj):
    """Validate native tabular pairs without changing their saved literal form."""
    previous = None
    if not obj.AmplitudeValues:
        raise ValueError(f"{obj.Name}: amplitude requires at least one time/value pair.")
    for line in obj.AmplitudeValues:
        tokens = [token.strip() for token in line.split(",")]
        # Native data lines may pad the final complete pair with empty fields.
        # Retain the literal line below; only validation ignores this padding.
        while tokens and not tokens[-1]:
            tokens.pop()
        if (
            "\n" in line
            or "\r" in line
            or len(tokens) not in (2, 4, 6, 8)
            or any(not _NUMBER.fullmatch(token) for token in tokens)
        ):
            raise ValueError(
                f"{obj.Name}: amplitude data must contain one to four numeric time/value "
                "pairs per line."
            )
        values = [float(token.replace("D", "E").replace("d", "e")) for token in tokens]
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"{obj.Name}: amplitude times and values must be finite.")
        for time in values[::2]:
            if previous is not None and time <= previous:
                raise ValueError(f"{obj.Name}: amplitude times must be strictly increasing.")
            previous = time


def write_amplitude(f, ccxwriter):

    # Validate every enabled table before writing any amplitude definitions.

    constraint_lists = [
        ccxwriter.member.cons_force,
        ccxwriter.member.cons_pressure,
        ccxwriter.member.cons_displacement,
        ccxwriter.member.cons_heatflux,
        ccxwriter.member.cons_temperature,
        ccxwriter.member.cons_bodyheatsource,
        ccxwriter.member.cons_rigidbody,
        ccxwriter.member.cons_initialtemperature,
    ]

    objects = []
    for constraint_list in constraint_lists:
        for entry in constraint_list:
            obj = entry["Object"]
            if obj.EnableAmplitude:
                _validate_amplitude(obj)
                objects.append(obj)
    for obj in objects:
        f.write(f"*AMPLITUDE, NAME={obj.Name}\n")
        for value in obj.AmplitudeValues:
            f.write(f"{value}\n")
        f.write("\n")
