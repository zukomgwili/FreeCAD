# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

from Base.Metadata import export
from Base.BaseClass import BaseClass
from Base.Metadata import constmethod
from Base.Quantity import Quantity
from typing import Final, List, Any


@export(
    Twin="Array2D",
    TwinPointer="Array2D",
    Namespace="Materials",
    Include="Mod/Material/App/MaterialValue.h",
    Delete=True,
    Constructor=True,
)
class Array2D(BaseClass):
    """
    2D Array of material properties.

    Author: DavidCarter (dcarter@davidcarter.ca)
    Licence: LGPL
    """

    Array: Final[List] = ...
    """The legacy 2 dimensional array, with all cells coerced to Quantity."""

    TypedArray: Final[List[List[Any]]] = ...
    """
    A detached, type-preserving copy of the native cells.

    Null cells are None. Supported values are Quantity, float, int, bool and str;
    numeric precision, units and embedded string nulls are preserved. Unsupported
    native cell types raise TypeError rather than being coerced. This read-only
    property does not change the legacy Array, getRow or getValue behaviour.
    """

    Dimensions: Final[int] = ...
    """The number of dimensions in the array, in this case 2."""

    Rows: int = ...
    """The number of rows in the array."""

    Columns: int = ...
    """The number of columns in the array."""

    @constmethod
    def getRow(self, value: int, /) -> List[Quantity]:
        """
        Legacy row read, coercing every cell to Quantity. Use TypedArray for
        exact native types and nulls.
        """
        ...

    @constmethod
    def getValue(self, row: int, column: int, /) -> Quantity:
        """
        Legacy cell read, coercing the value to Quantity. Use TypedArray for
        exact native types and nulls.
        """
        ...

    def setValue(self, row: int, column: int, value: str, /) -> None:
        """
        Set a Quantity parsed from a string at the given row and column.
        """
        ...
