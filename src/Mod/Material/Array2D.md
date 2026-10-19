# Native Array2D values

`Materials.Array2D.TypedArray` is a read-only, detached list of rows. It exposes
native cells as `None`, `Quantity`, `float`, `int`, `bool` or `str`, without
converting numeric cells to Quantity. Quantities retain their native value and
unit; floats retain stored precision; strings retain Unicode and embedded NULs.
Unsupported native cell types raise `TypeError` rather than being stringified.
Malformed native dimensions or row layouts raise `ValueError`.
Changing a returned list or Quantity does not change the native array.

The existing `Array`, `getRow` and `getValue` interfaces deliberately retain
their legacy Quantity coercion. Use `TypedArray` when actual types or nulls
matter. The existing `setValue` continues to parse its string argument as a
Quantity; the native material editor can author other declared column types.

## Material-card persistence

New Array2D material-card values use a versioned flow map inside the historical
outer sequence. Its format identifier is `FreeCAD.Array2D`, version `1`, with
explicit `Columns` and `Rows`. Each cell records its native type and null state.
Numeric widths and integer signedness are explicit. Floating-point and Quantity
values use hexadecimal IEEE bit patterns, and Quantity units use all eight
native unit exponents. Strings use hexadecimal UTF-16 code units so even NULs
and unpaired surrogates roundtrip. Quantity display-format preferences are not
part of this physical-value format.

Empty dimensions, typed-null cells and actual typed value changes must survive
ordinary material saves, including inherited material saves. In the new typed
format, unsupported cell types, malformed versions/rows/cells, incompatible
numeric widths and out-of-range integers are rejected instead of being silently
coerced. The historical reader retains its legacy row-layout behavior; the typed
accessor and writer reject malformed native arrays.
Platform-native integer types with incompatible widths or ranges are rejected
on another platform rather than being reinterpreted or truncated.

The new reader still accepts historical one-element and default-plus-array
two-element Quantity-string representations. This is backward **reading**
compatibility, not forward compatibility: older FreeCAD versions cannot read
the new typed representation. Do not open and resave a new typed material card
with an older version. No existing material library is automatically rewritten.

`ShapeMaterial` in an FCStd document still references a material by UUID; it does
not embed an unsaved material's complete contents. Save the material to an
available library before relying on document close/reopen, and retain that
library with the project. The Array2D change does not alter that document format.

Array3D and scalar persistence are unchanged. Separate Array3D precision and
inherited-save qualification is tracked as FreeCAD-b7d.

## FEM provenance

FEM mesh and native-accounting fingerprints use `TypedArray`, retaining Python
semantic types, nulls, units and precision. Native integer widths map to Python
`int`, Float32/Float64 to `float`, and supported typed nulls to `None`; fingerprints
do not distinguish storage-width or null-metatype changes alone. Genuine semantic
cell edits change the identity; read-only wrapper copies do not. Missing typed
interfaces, unsupported values,
nonfinite populated inputs and ambiguous material declaration namespaces still
fail closed. Existing historical results are not promoted to current: regenerate
requests through the ordinary writer before a new solve when required.

These are software value/persistence guarantees, not engineering, equilibrium,
mesh-convergence or building-design acceptance.
