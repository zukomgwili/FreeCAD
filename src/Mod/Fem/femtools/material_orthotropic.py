# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native orthotropic elasticity and material-frame validation.

Moduli are returned in MPa, in CalculiX engineering-constant order. Poisson
ratio ij is minus transverse strain j / axial strain i under uniaxial stress i.
The reciprocal ratios are not independent: nu_ji / E_j = nu_ij / E_i.
"""

import hashlib
import math

import FreeCAD


def is_orthotropic(obj):
    return ("ElasticityModel" in obj.PropertiesList
            and obj.ElasticityModel == "Orthotropic")


def engineering_constants(obj):
    """Return E1,E2,E3,nu12,nu13,nu23,G12,G13,G23; reject unstable data."""
    moduli = [getattr(obj, name).getValueAs("MPa").Value for name in (
        "YoungsModulus1", "YoungsModulus2", "YoungsModulus3",
        "ShearModulus12", "ShearModulus13", "ShearModulus23",
    )]
    ratios = [getattr(obj, "PoissonRatio" + pair) for pair in ("12", "13", "23")]
    if any(not math.isfinite(value) or value <= 0 for value in moduli):
        raise ValueError("Orthotropic Young's and shear moduli must be finite and positive.")
    if any(not math.isfinite(value) for value in ratios):
        raise ValueError("Orthotropic Poisson ratios must be finite.")
    constants = tuple(moduli[:3] + ratios + moduli[3:])
    _check_compliance(constants)
    # The standard CalculiX writer serializes 13 significant figures. A law
    # just inside the stability boundary can become singular when rounded.
    try:
        _check_compliance(tuple(float(f"{value:.13G}") for value in constants))
    except ValueError as error:
        raise ValueError("Orthotropic compliance is unstable at output precision.") from error
    return constants


def _check_compliance(constants):
    # Symmetric compliance, diagonally scaled to unit diagonal. Positive shear
    # moduli plus Sylvester's criterion on this 3x3 normal block ensure positive
    # strain energy. Unlike isotropy, individual Poisson ratios need not be <0.5.
    e1, e2, e3 = constants[:3]
    ratios = constants[3:6]
    a = -ratios[0] * math.sqrt(e2) / math.sqrt(e1)
    b = -ratios[1] * math.sqrt(e3) / math.sqrt(e1)
    c = -ratios[2] * math.sqrt(e3) / math.sqrt(e2)
    determinant = 1 + 2 * a * b * c - a * a - b * b - c * c
    if (not math.isfinite(determinant) or 1 - a * a <= 0 or determinant <= 0):
        raise ValueError("Orthotropic engineering constants require positive-definite compliance.")


def material_rotation(obj):
    """Map material axes into global mesh axes, following a placed reference."""
    rotation = obj.MaterialOrientation
    reference = obj.MaterialOrientationReference
    if reference:
        if reference == obj or "Placement" not in reference.PropertiesList:
            raise ValueError("Material orientation reference must be a placed object.")
        # App::Link exposes Placement but is not a GeoFeature and has no
        # getGlobalPlacement(). Follow its native parent geometry groups too.
        placement = reference.Placement
        parent = reference.getParentGeoFeatureGroup()
        while parent:
            placement = parent.Placement * placement
            parent = parent.getParentGeoFeatureGroup()
        rotation = placement.Rotation * rotation
    for axis in (FreeCAD.Vector(1, 0, 0), FreeCAD.Vector(0, 1, 0)):
        if not all(math.isfinite(value) for value in rotation.multVec(axis)):
            raise ValueError("Material orientation must be finite.")
    return rotation


def validation_errors(obj):
    """Return basic material errors for the GUI and analysis preflight."""
    if not is_orthotropic(obj):
        return []
    errors = []
    if obj.Category != "Solid":
        errors.append("Orthotropic elasticity requires a solid-category material.")
    for check in (engineering_constants, material_rotation):
        try:
            check(obj)
        except (ValueError, TypeError, AttributeError, OverflowError) as error:
            errors.append(str(error))
    return errors


def orientation_name(obj):
    name = "ORIENT_" + obj.Name
    if len(name) > 80:
        name = name[:67] + "_" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
    return name


def require_isotropic_material(obj, solver_name):
    """Prevent older mechanical exporters silently using the isotropic card."""
    if is_orthotropic(obj):
        raise ValueError(
            f"{obj.Label}: native orthotropic elasticity is not supported by the "
            f"{solver_name} exporter; use CalculiX or explicitly select Isotropic."
        )
