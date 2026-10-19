# SPDX-License-Identifier: LGPL-2.1-or-later
"""Value-based native material leaves shared by FEM input fingerprints.

Materials::PropertyMaterial returns a new native copy on every read. Its str()
contains that copy's address, not its contents. Keep identity, model declarations
and full typed values instead; never strip addresses or ignore material inputs.
"""

import math

import FreeCAD
import Materials


def _material_value(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Cannot fingerprint a nonfinite native material value")
        return {"float": value.hex()}
    if isinstance(value, FreeCAD.Units.Quantity):
        return {
            "quantity": _material_value(value.Value),
            "unit": list(value.Unit.Signature),
        }
    if isinstance(value, (list, tuple)):
        return [_material_value(item) for item in value]
    if isinstance(value, Materials.Array2D):
        rows = value.Array
        if any(
            cell.Value == 0 and not any(cell.Unit.Signature)
            for row in rows
            for cell in row
        ):
            # A null native QVariant cell is exposed as a dimensionless zero,
            # indistinguishable from an authored zero through the current API.
            raise ValueError(
                "Cannot fingerprint native 2D material arrays with ambiguous null/zero cells"
            )
        return {
            "array2d": _material_value(rows),
            "rows": value.Rows,
            "columns": value.Columns,
        }
    if isinstance(value, Materials.Array3D):
        return {
            "array3d": _material_value(value.Array),
            "columns": value.Columns,
            "depths": [
                _material_value(value.getDepthValue(i)) for i in range(value.Depth)
            ],
        }
    raise ValueError(
        f"Cannot fingerprint native material value type {type(value).__name__}"
    )


def _declaration(prop):
    return {
        "name": prop.Name,
        "type": prop.Type,
        "units": prop.Units,
        "inheritance": prop.Inheritance,
        "inherited": prop.Inherited,
        "columns": [_declaration(column) for column in prop.Columns],
    }


def _property_value(getter, key, prop):
    # An unset native Quantity is internally NaN, not a populated nonfinite
    # value. Empty arrays still have dimensions/columns that must be retained.
    if prop.Empty and prop.Type == "Quantity":
        return None
    if (
        prop.Type == "2DArray"
        and not prop.Empty
        and any(column.Type != "Quantity" for column in prop.Columns)
    ):
        # The native Array2D Python getter converts every QVariant cell to a
        # Quantity, losing raw Float/Integer cells written by the native GUI.
        raise ValueError(
            "Cannot fingerprint native 2D material arrays with non-Quantity columns"
        )
    return _material_value(getter(key))


def property_value(value):
    """Encode a material by value; preserve existing scalar behavior otherwise.

    The legacy string dictionaries round quantities and can discard lists and
    arrays. Use typed getters, including the separate Array3D depth coordinates.
    Library getters are intentionally not used: an unsaved material has no library.
    """
    if not isinstance(value, Materials.Material):
        return str(value)
    props = value.PropertyObjects
    if any(
        value.hasPhysicalProperty(key) and value.hasAppearanceProperty(key)
        for key in props
    ):
        # PropertyObjects merges the two namespaces and cannot supply both
        # declarations when names collide. Never use one domain's Empty/type
        # metadata to decide whether the other domain's value can be omitted.
        raise ValueError("Ambiguous native material physical/appearance property names")
    return {
        "native_material": {
            name: getattr(value, name)
            for name in (
                "UUID",
                "Name",
                "Directory",
                "Parent",
                "Description",
                "URL",
                "Reference",
                "Author",
                "License",
            )
        },
        "tags": sorted(value.Tags),
        "physical_models": sorted(value.PhysicalModels),
        "appearance_models": sorted(value.AppearanceModels),
        "declarations": {
            key: dict(_declaration(prop), empty=prop.Empty)
            for key, prop in sorted(props.items())
        },
        "physical": {
            key: _property_value(value.getPhysicalValue, key, props[key])
            for key in sorted(props)
            if value.hasPhysicalProperty(key)
        },
        "appearance": {
            key: _property_value(value.getAppearanceValue, key, props[key])
            for key in sorted(props)
            if value.hasAppearanceProperty(key)
        },
        "legacy": dict(sorted(value.LegacyProperties.items())),
    }
