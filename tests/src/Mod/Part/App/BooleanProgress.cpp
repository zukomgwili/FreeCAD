// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <atomic>
#include <algorithm>
#include <vector>

#include <BRep_Builder.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepGProp.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <GProp_GProps.hxx>
#include <Message_ProgressIndicator.hxx>
#include <Standard_ConstructionError.hxx>
#include <TopoDS_Compound.hxx>

#include <Mod/Part/App/FCBRepAlgoAPI_BooleanOperation.h>

namespace
{
class RecordingProgress: public Message_ProgressIndicator
{
public:
    explicit RecordingProgress(bool cancel = false)
        : cancelAtIntermediate(cancel)
    {}

    std::vector<double> positions;
    std::atomic<bool> cancelled {false};
    double cancelledAt {0.0};

protected:
    bool UserBreak() override
    {
        return cancelled.load();
    }

    void Show(const Message_ProgressScope&, bool) override
    {
        const double position = GetPosition();
        positions.push_back(position);
        if (cancelAtIntermediate && position > 0.0 && position < 1.0) {
            if (!cancelled.exchange(true)) {
                cancelledAt = position;
            }
        }
    }

private:
    bool cancelAtIntermediate;
};

TopoDS_Shape box(double x)
{
    return BRepPrimAPI_MakeBox(gp_Pnt(x, 0, 0), 10, 10, 10).Shape();
}

TopoDS_Compound compound(const std::vector<TopoDS_Shape>& children)
{
    BRep_Builder builder;
    TopoDS_Compound result;
    builder.MakeCompound(result);
    for (const auto& child : children) {
        builder.Add(result, child);
    }
    return result;
}

void configure(FCBRepAlgoAPI_BooleanOperation& operation, bool nestedTools = false)
{
    TopTools_ListOfShape arguments;
    arguments.Append(compound({compound({box(0), box(20)}), box(40)}));
    TopTools_ListOfShape tools;
    const auto cutter = BRepPrimAPI_MakeBox(gp_Pnt(5, -5, -5), 50, 20, 20).Shape();
    tools.Append(nestedTools ? compound({compound({cutter})}) : cutter);
    operation.SetArguments(arguments);
    operation.SetTools(tools);
    operation.SetOperation(BOPAlgo_CUT);
}

void configureFusedTools(FCBRepAlgoAPI_BooleanOperation& operation)
{
    configure(operation);
    // Intersecting tools require actual fuse kernel work; disjoint tools may
    // legitimately report only the completed fuse subrange.
    const auto first = BRepPrimAPI_MakeBox(gp_Pnt(5, -5, -5), 15, 20, 20).Shape();
    const auto second = BRepPrimAPI_MakeBox(gp_Pnt(15, -5, -5), 10, 20, 20).Shape();
    TopTools_ListOfShape tools;
    tools.Append(compound({compound({first, second})}));
    operation.SetTools(tools);
}

double volume(const TopoDS_Shape& shape)
{
    GProp_GProps properties;
    BRepGProp::VolumeProperties(shape, properties);
    return properties.Mass();
}
}  // namespace

TEST(BooleanProgress, NestedArgumentsReportIntermediateProgress)
{
    FCBRepAlgoAPI_BooleanOperation operation;
    configure(operation);
    Handle(RecordingProgress) progress = new RecordingProgress;
    operation.Build(progress->Start());
    ASSERT_TRUE(operation.IsDone());
    EXPECT_TRUE(BRepCheck_Analyzer(operation.Shape()).IsValid());
    EXPECT_NEAR(volume(operation.Shape()), 500.0, 1e-7);
    EXPECT_GT(progress->positions.size(), 2U);
    EXPECT_TRUE(std::any_of(progress->positions.begin(), progress->positions.end(), [](double p) {
        return p > 0.0 && p < 1.0;
    }));
}

TEST(BooleanProgress, NestedArgumentsObserveCancellation)
{
    FCBRepAlgoAPI_BooleanOperation operation;
    configure(operation);
    Handle(RecordingProgress) progress = new RecordingProgress(true);
    EXPECT_THROW(operation.Build(progress->Start()), Standard_ConstructionError);
    EXPECT_TRUE(progress->cancelled.load());
    EXPECT_EQ(operation.Arguments().First().ShapeType(), TopAbs_COMPOUND);
}

TEST(BooleanProgress, NestedToolsObserveCancellation)
{
    FCBRepAlgoAPI_BooleanOperation operation;
    configure(operation, true);
    Handle(RecordingProgress) progress = new RecordingProgress(true);
    EXPECT_THROW(operation.Build(progress->Start()), Standard_ConstructionError);
    EXPECT_TRUE(progress->cancelled.load());
    EXPECT_EQ(operation.Operation(), BOPAlgo_CUT);
    EXPECT_EQ(operation.Arguments().First().ShapeType(), TopAbs_COMPOUND);
    EXPECT_EQ(operation.Tools().First().ShapeType(), TopAbs_COMPOUND);
}

TEST(BooleanProgress, FusedCompoundToolsPreserveGeometryAndOperands)
{
    FCBRepAlgoAPI_BooleanOperation operation;
    configureFusedTools(operation);
    const auto originalArgument = operation.Arguments().First();
    const auto originalTool = operation.Tools().First();
    Handle(RecordingProgress) progress = new RecordingProgress;
    operation.Build(progress->Start());
    ASSERT_TRUE(operation.IsDone());
    EXPECT_TRUE(BRepCheck_Analyzer(operation.Shape()).IsValid());
    EXPECT_NEAR(volume(operation.Shape()), 2000.0, 1e-7);
    EXPECT_EQ(operation.Operation(), BOPAlgo_CUT);
    ASSERT_EQ(operation.Arguments().Size(), 1);
    ASSERT_EQ(operation.Tools().Size(), 1);
    EXPECT_TRUE(operation.Arguments().First().IsSame(originalArgument));
    EXPECT_TRUE(operation.Tools().First().IsSame(originalTool));
    EXPECT_TRUE(std::any_of(progress->positions.begin(), progress->positions.end(), [](double p) {
        return p > 0.0 && p < 0.5;
    }));
    EXPECT_TRUE(std::any_of(progress->positions.begin(), progress->positions.end(), [](double p) {
        return p > 0.5 && p < 1.0;
    }));
}

TEST(BooleanProgress, FusedCompoundToolsObserveCancellationDuringFuse)
{
    FCBRepAlgoAPI_BooleanOperation operation;
    configureFusedTools(operation);
    const auto originalArgument = operation.Arguments().First();
    const auto originalTool = operation.Tools().First();
    Handle(RecordingProgress) progress = new RecordingProgress(true);
    EXPECT_THROW(operation.Build(progress->Start()), Standard_ConstructionError);
    EXPECT_TRUE(progress->cancelled.load());
    EXPECT_GT(progress->cancelledAt, 0.0);
    EXPECT_LT(progress->cancelledAt, 0.5);
    EXPECT_EQ(operation.Operation(), BOPAlgo_CUT);
    ASSERT_EQ(operation.Arguments().Size(), 1);
    ASSERT_EQ(operation.Tools().Size(), 1);
    EXPECT_TRUE(operation.Arguments().First().IsSame(originalArgument));
    EXPECT_TRUE(operation.Tools().First().IsSame(originalTool));
}

TEST(BooleanProgress, EmptyCompoundPreservesOperandsAndProducesEmptyGeometry)
{
    FCBRepAlgoAPI_BooleanOperation operation;
    const auto empty = compound({});
    TopTools_ListOfShape arguments;
    arguments.Append(empty);
    TopTools_ListOfShape tools;
    tools.Append(box(0));
    operation.SetArguments(arguments);
    operation.SetTools(tools);
    operation.SetOperation(BOPAlgo_CUT);
    Handle(RecordingProgress) progress = new RecordingProgress;
    EXPECT_NO_THROW(operation.Build(progress->Start()));
    EXPECT_EQ(operation.Operation(), BOPAlgo_CUT);
    EXPECT_TRUE(operation.Arguments().First().IsSame(empty));
    EXPECT_FALSE(operation.Shape().IsNull());
    EXPECT_EQ(operation.Shape().ShapeType(), TopAbs_COMPOUND);
    EXPECT_NEAR(volume(operation.Shape()), 0.0, 1e-7);
    EXPECT_TRUE(BRepCheck_Analyzer(operation.Shape()).IsValid());
    EXPECT_FALSE(progress->cancelled.load());
}

TEST(BooleanProgress, DirectCutReportsKernelProgress)
{
    FCBRepAlgoAPI_BooleanOperation operation;
    TopTools_ListOfShape arguments;
    arguments.Append(box(0));
    TopTools_ListOfShape tools;
    tools.Append(box(5));
    operation.SetArguments(arguments);
    operation.SetTools(tools);
    operation.SetOperation(BOPAlgo_CUT);
    Handle(RecordingProgress) progress = new RecordingProgress;
    operation.Build(progress->Start());
    ASSERT_TRUE(operation.IsDone());
    EXPECT_TRUE(BRepCheck_Analyzer(operation.Shape()).IsValid());
    EXPECT_NEAR(volume(operation.Shape()), 500.0, 1e-7);
    EXPECT_TRUE(std::any_of(progress->positions.begin(), progress->positions.end(), [](double p) {
        return p > 0.0 && p < 1.0;
    }));
}

TEST(BooleanProgress, DirectCutObservesKernelCancellation)
{
    FCBRepAlgoAPI_BooleanOperation operation;
    TopTools_ListOfShape arguments;
    const auto argument = box(0);
    arguments.Append(argument);
    TopTools_ListOfShape tools;
    const auto tool = box(5);
    tools.Append(tool);
    operation.SetArguments(arguments);
    operation.SetTools(tools);
    operation.SetOperation(BOPAlgo_CUT);
    Handle(RecordingProgress) progress = new RecordingProgress(true);
    EXPECT_THROW(operation.Build(progress->Start()), Standard_ConstructionError);
    EXPECT_TRUE(progress->cancelled.load());
    EXPECT_GT(progress->cancelledAt, 0.0);
    EXPECT_LT(progress->cancelledAt, 1.0);
    EXPECT_EQ(operation.Operation(), BOPAlgo_CUT);
    EXPECT_TRUE(operation.Arguments().First().IsSame(argument));
    EXPECT_TRUE(operation.Tools().First().IsSame(tool));
}
