// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2024 Eric Price (CorvusCorax)                           *
 *                      <eric.price[at]tuebingen.mpg.de>                   *
 *                                                                         *
 *   This file is part of FreeCAD.                                         *
 *                                                                         *
 *   FreeCAD is free software: you can redistribute it and/or modify it    *
 *   under the terms of the GNU Lesser General Public License as           *
 *   published by the Free Software Foundation, either version 2.1 of the  *
 *   License, or (at your option) any later version.                       *
 *                                                                         *
 *   FreeCAD is distributed in the hope that it will be useful, but        *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
 *   Lesser General Public License for more details.                       *
 *                                                                         *
 *   You should have received a copy of the GNU Lesser General Public      *
 *   License along with FreeCAD. If not, see                               *
 *   <https://www.gnu.org/licenses/>.                                      *
 *                                                                         *
 **************************************************************************/

/**
 * FCBRepAlgoAPI provides a wrapper for various OCCT functions.
 */

#include <FCBRepAlgoAPI_BooleanOperation.h>
#include <sstream>
#include <BRepBndLib.hxx>
#include <Bnd_Box.hxx>
#include <BOPAlgo_Alerts.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepBuilderAPI_Copy.hxx>
#include <BRepTools_ShapeSet.hxx>
#include <BRep_Builder.hxx>
#include <Standard_Failure.hxx>
#include <TopTools_FormatVersion.hxx>
#include <TopoDS_Shape.hxx>
#include <TopoDS_Iterator.hxx>
#include <Precision.hxx>
#include <FuzzyHelper.h>
#include <SignalException.h>
#include <Base/Console.h>

namespace
{

void normalizeTransientFlags(TopoDS_Shape shape)
{
    // Boolean checks may change these bookkeeping flags without changing topology or geometry.
    shape.Free(false);
    shape.Modified(false);
    shape.Checked(false);
    for (TopoDS_Iterator child(shape); child.More(); child.Next()) {
        normalizeTransientFlags(child.Value());
    }
}

bool haveIdenticalBRep(const TopoDS_Shape& first, const TopoDS_Shape& second)
{
    if (first.IsNull() || second.IsNull()) {
        return false;
    }

    if (first.IsEqual(second)) {
        return true;
    }

    if (first.ShapeType() != second.ShapeType()) {
        return false;
    }

    try {
        Bnd_Box firstBounds;
        Bnd_Box secondBounds;
        BRepBndLib::Add(first, firstBounds);
        BRepBndLib::Add(second, secondBounds);
        if (firstBounds.IsVoid() != secondBounds.IsVoid()) {
            return false;
        }
        if (!firstBounds.IsVoid()
            && (!firstBounds.CornerMin().IsEqual(secondBounds.CornerMin(), Precision::Confusion())
                || !firstBounds.CornerMax().IsEqual(
                    secondBounds.CornerMax(),
                    Precision::Confusion()
                ))) {
            return false;
        }

        TopoDS_Shape firstCopy = BRepBuilderAPI_Copy(first, false, false).Shape();
        TopoDS_Shape secondCopy = BRepBuilderAPI_Copy(second, false, false).Shape();
        normalizeTransientFlags(firstCopy);
        normalizeTransientFlags(secondCopy);

        std::ostringstream firstStream;
        std::ostringstream secondStream;
        BRepTools_ShapeSet firstSet(false);
        firstSet.SetFormatNb(TopTools_FormatVersion_VERSION_1);
        firstSet.Add(firstCopy);
        firstSet.Write(firstStream);
        firstSet.Write(firstCopy, firstStream);
        BRepTools_ShapeSet secondSet(false);
        secondSet.SetFormatNb(TopTools_FormatVersion_VERSION_1);
        secondSet.Add(secondCopy);
        secondSet.Write(secondStream);
        secondSet.Write(secondCopy, secondStream);
        return firstStream.str() == secondStream.str();
    }
    catch (const Standard_Failure&) {
        return false;
    }
}

}  // namespace

FCBRepAlgoAPI_BooleanOperation::FCBRepAlgoAPI_BooleanOperation()
{
    SetRunParallel(Standard_True);
    SetNonDestructive(Standard_True);
}


FCBRepAlgoAPI_BooleanOperation::FCBRepAlgoAPI_BooleanOperation(
    const TopoDS_Shape& theS1,
    const TopoDS_Shape& theS2,
    const BOPAlgo_Operation theOperation
)
    : BRepAlgoAPI_BooleanOperation(theS1, theS2, theOperation)
{
    if (!BRepCheck_Analyzer(theS1).IsValid()) {
        Base::Console().warning("Base shape is not valid for boolean operation");
    }

    if (!BRepCheck_Analyzer(theS2).IsValid()) {
        Base::Console().warning("Tool shape is not valid for boolean operation");
    }

    setAutoFuzzy();
    SetRunParallel(Standard_True);
    SetNonDestructive(Standard_True);
}

void FCBRepAlgoAPI_BooleanOperation::setAutoFuzzy()
{
    FCBRepAlgoAPIHelper::setAutoFuzzy(this);
}


void FCBRepAlgoAPIHelper::setAutoFuzzy(BRepAlgoAPI_BooleanOperation* op)
{
    Bnd_Box bounds;
    for (TopTools_ListOfShape::Iterator it(op->Arguments()); it.More(); it.Next()) {
        BRepBndLib::Add(it.Value(), bounds);
    }
    for (TopTools_ListOfShape::Iterator it(op->Tools()); it.More(); it.Next()) {
        BRepBndLib::Add(it.Value(), bounds);
    }
    op->SetFuzzyValue(
        Part::FuzzyHelper::getBooleanFuzzy() * sqrt(bounds.SquareExtent()) * Precision::Confusion()
    );
}

void FCBRepAlgoAPIHelper::setAutoFuzzy(BRepAlgoAPI_BuilderAlgo* op)
{
    Bnd_Box bounds;
    for (TopTools_ListOfShape::Iterator it(op->Arguments()); it.More(); it.Next()) {
        BRepBndLib::Add(it.Value(), bounds);
    }
    op->SetFuzzyValue(
        Part::FuzzyHelper::getBooleanFuzzy() * sqrt(bounds.SquareExtent()) * Precision::Confusion()
    );
}

void FCBRepAlgoAPI_BooleanOperation::Build()
{
    Message_ProgressRange progressRange;
    Build(progressRange);
}

void FCBRepAlgoAPI_BooleanOperation::Build(const Message_ProgressRange& progressRange)
{
    Part::SignalException sig;
    if (progressRange.UserBreak()) {
        throw Standard_ConstructionError("User aborted");
    }
    if (myOperation == BOPAlgo_CUT && myArguments.Size() == 1 && myTools.Size() == 1
        && myTools.First().ShapeType() == TopAbs_COMPOUND) {
        // cut argument and compound tool
        TopTools_ListOfShape myOriginalArguments = myArguments;
        TopTools_ListOfShape myOriginalTools = myTools;
        RecursiveCutFusedTools(myOriginalArguments, myOriginalTools.First());
        myArguments = myOriginalArguments;
        myTools = myOriginalTools;
    }
    else if (
        myOperation == BOPAlgo_CUT && myArguments.Size() == 1
        && myArguments.First().ShapeType() == TopAbs_COMPOUND
    ) {
        // cut compound argument
        TopTools_ListOfShape myOriginalArguments = myArguments;
        RecursiveCutCompound(myOriginalArguments.First());
        myArguments = myOriginalArguments;
    }
    else {
#if OCC_VERSION_HEX >= 0x070600
        BRepAlgoAPI_BooleanOperation::Build(progressRange);
#else
        BRepAlgoAPI_BooleanOperation::Build();
#endif

        // Some valid shapes with located sub-shapes make OCCT report success for A - A while
        // returning an invalid copy of A. Recover only when the operands have byte-for-byte
        // identical canonical native BRep representations; geometrically similar operands must
        // still be handled by the Boolean algorithm.
        if (myOperation == BOPAlgo_CUT && myArguments.Size() == 1 && myTools.Size() == 1
            && !myShape.IsNull() && !BRepCheck_Analyzer(myShape).IsValid()
            && HasWarning(STANDARD_TYPE(BOPAlgo_AlertSolidBuilderUnusedFaces))
            && haveIdenticalBRep(myArguments.First(), myTools.First())) {
            TopoDS_Compound emptyResult;
            BRep_Builder builder;
            builder.MakeCompound(emptyResult);
            myShape = emptyResult;
            Done();
        }
    }
    if (progressRange.UserBreak()) {
        throw Standard_ConstructionError("User aborted");
    }
}

void FCBRepAlgoAPI_BooleanOperation::RecursiveAddTools(const TopoDS_Shape& theTool)
{
    TopoDS_Iterator it(theTool);
    for (; it.More(); it.Next()) {
        if (it.Value().ShapeType() == TopAbs_COMPOUND) {
            RecursiveAddTools(it.Value());
        }
        else {
            myTools.Append(it.Value());
        }
    }
}

void FCBRepAlgoAPI_BooleanOperation::RecursiveCutFusedTools(
    const TopTools_ListOfShape& theOriginalArguments,
    const TopoDS_Shape& theTool
)
{
    // get a list of shapes in the tool compound
    myTools.Clear();
    RecursiveAddTools(theTool);

    // if tool consists of two or more shapes, fuse them together
    if (myTools.Size() >= 2) {
        myArguments.Clear();
        myArguments.Append(myTools.First());
        myTools.RemoveFirst();
        myOperation = BOPAlgo_FUSE;
        Build();

        // restore original state
        myOperation = BOPAlgo_CUT;
        myArguments = theOriginalArguments;

        if (!IsDone()) {
            myShape = {};
            return;
        }

        // use fused shape as new tool
        // if the original tools didn't all touch, the fused shape will be a compound
        // which we convert into a list of shapes so we don't attempt to fuse them again
        myTools.Clear();
        RecursiveAddTools(myShape);
    }

    // do the cut
    Build();
}

void FCBRepAlgoAPI_BooleanOperation::RecursiveCutCompound(const TopoDS_Shape& theArgument)
{
    BRep_Builder builder;
    TopoDS_Compound comp;
    builder.MakeCompound(comp);

    // iterate through shapes in argument compound and cut each one with the tool
    TopoDS_Iterator it(theArgument);
    for (; it.More(); it.Next()) {
        myArguments.Clear();
        myArguments.Append(it.Value());
        Build();

        if (!IsDone()) {
            myShape = {};
            return;
        }

        builder.Add(comp, myShape);
    }

    // result is a compound of individual cuts
    myShape = comp;
}
