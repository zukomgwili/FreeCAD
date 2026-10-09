// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRep_Builder.hxx>
#include <Geom_Ellipse.hxx>
#include <TopExp.hxx>
#include "PartTestHelpers.h"
#include <Mod/Part/App/TopoShape.h>
#include "src/App/InitApplication.h"


class TopoShapeTest: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }

    void SetUp() override
    {
        Base::Interpreter().runString("import Part");
        _docName = App::GetApplication().getUniqueDocumentName("test");
        App::GetApplication().newDocument(_docName.c_str(), "testUser");
        _hasher = Base::Reference<App::StringHasher>(new App::StringHasher);
        ASSERT_EQ(_hasher.getRefCount(), 1);
    }

    void TearDown() override
    {
        App::GetApplication().closeDocument(_docName.c_str());
    }


private:
    std::string _docName;
    Data::ElementIDRefs _sid;
    App::StringHasherRef _hasher;
};

// clang-format off
TEST_F(TopoShapeTest, TestElementTypeFace1)
{
    EXPECT_EQ(Part::TopoShape::getElementTypeAndIndex("Face1"),
              std::make_pair(std::string("Face"), 1UL));
}

TEST_F(TopoShapeTest, TestElementTypeEdge12)
{
    EXPECT_EQ(Part::TopoShape::getElementTypeAndIndex("Edge12"),
              std::make_pair(std::string("Edge"), 12UL));
}

TEST_F(TopoShapeTest, TestElementTypeVertex3)
{
    EXPECT_EQ(Part::TopoShape::getElementTypeAndIndex("Vertex3"),
              std::make_pair(std::string("Vertex"), 3UL));
}

TEST_F(TopoShapeTest, TestElementTypeFacer)
{
    EXPECT_EQ(Part::TopoShape::getElementTypeAndIndex("Facer"),
              std::make_pair(std::string(), 0UL));
}

TEST_F(TopoShapeTest, TestElementTypeVertex)
{
    EXPECT_EQ(Part::TopoShape::getElementTypeAndIndex("Vertex"),
              std::make_pair(std::string(), 0UL));
}

TEST_F(TopoShapeTest, TestElementTypeEmpty)
{
    EXPECT_EQ(Part::TopoShape::getElementTypeAndIndex(""),
              std::make_pair(std::string(), 0UL));
}

TEST_F(TopoShapeTest, TestElementTypeNull)
{
    EXPECT_EQ(Part::TopoShape::getElementTypeAndIndex(nullptr),
              std::make_pair(std::string(), 0UL));
}

TEST_F(TopoShapeTest, TestElementTypeWithHash)
{
    EXPECT_EQ(Part::TopoShape::getElementTypeAndIndex(";#7:1;:G0;XTR;:H11a6:8,F.Face3"),
              std::make_pair(std::string("Face"), 3UL));
}

TEST_F(TopoShapeTest, TestElementTypeWithSubelements)
{
    EXPECT_EQ(Part::TopoShape::getElementTypeAndIndex("Part.Body.Pad.Face3"),
              std::make_pair(std::string(), 0UL));
}

TEST_F(TopoShapeTest, TestElementTypeNonMatching)
{
    for (std::array elements = {"Face0", "Face01", "XFace3", "Face3extra"};
         const auto& element : elements) {
        EXPECT_EQ(Part::TopoShape::getElementTypeAndIndex(element),
                  std::make_pair(std::string(), 0UL));
    }
}

TEST_F(TopoShapeTest, TestTypeFace1)
{
    EXPECT_EQ(Part::TopoShape::getTypeAndIndex("Face1"),
              std::make_pair(std::string("Face"), 1UL));
}

TEST_F(TopoShapeTest, TestTypeEdge12)
{
    EXPECT_EQ(Part::TopoShape::getTypeAndIndex("Edge12"),
              std::make_pair(std::string("Edge"), 12UL));
}

TEST_F(TopoShapeTest, TestTypeVertex3)
{
    EXPECT_EQ(Part::TopoShape::getTypeAndIndex("Vertex3"),
              std::make_pair(std::string("Vertex"), 3UL));
}

TEST_F(TopoShapeTest, TestTypeFacer)
{
    EXPECT_EQ(Part::TopoShape::getTypeAndIndex("Facer"),
              std::make_pair(std::string("Facer"), 0UL));
}

TEST_F(TopoShapeTest, TestTypeVertex)
{
    EXPECT_EQ(Part::TopoShape::getTypeAndIndex("Vertex"),
              std::make_pair(std::string("Vertex"), 0UL));
}

TEST_F(TopoShapeTest, TestTypeEmpty)
{
    EXPECT_EQ(Part::TopoShape::getTypeAndIndex(""),
              std::make_pair(std::string(), 0UL));
}

TEST_F(TopoShapeTest, TestTypeNull)
{
    EXPECT_EQ(Part::TopoShape::getTypeAndIndex(nullptr),
              std::make_pair(std::string(), 0UL));
}

TEST_F(TopoShapeTest, TestGetSubshape)
{
    // Arrange
    auto [cube1, cube2] = PartTestHelpers::CreateTwoTopoShapeCubes();
    // Act
    auto face = cube1.getSubShape("Face2");
    auto vertex = cube2.getSubShape(TopAbs_VERTEX,2);
    auto silentFail = cube1.getSubShape("NotThere", true);
    // Assert
    EXPECT_EQ(face.ShapeType(), TopAbs_FACE);
    EXPECT_EQ(vertex.ShapeType(), TopAbs_VERTEX);
    EXPECT_TRUE(silentFail.IsNull());
    EXPECT_THROW(cube1.getSubShape("Face7"), Base::IndexError);          // Out of range
    EXPECT_THROW(cube1.getSubShape("WOOHOO", false), Base::ValueError);  // Invalid
}

TEST_F(TopoShapeTest, TestBrepRoundTripPreservesValidityNearVertexTolerance)
{
    // This edge models the minimal failure from a native ArchPipe tee. Its final vertex is valid,
    // but lies close enough to its tolerance boundary that BREP text rounding used to move it
    // outside the serialized tolerance.
    const gp_Pnt center(8325.0, 11600.000000000002, -1647.2624999999996);
    const gp_Dir normal(-0.7071067811865475, 0.7071067811865477, -1.6957013329920143e-16);
    const gp_Dir xDirection(-0.7069963216402694, -0.7069963216402692, 0.01767490804100669);
    const Handle(Geom_Ellipse) ellipse =
        new Geom_Ellipse(gp_Ax2(center, normal, xDirection), 77.78782239206852, 55.0);
    BRepBuilderAPI_MakeEdge makeEdge(ellipse, 0.0, 1.570796326794897);
    ASSERT_TRUE(makeEdge.IsDone());

    TopoDS_Edge edge = makeEdge.Edge();
    const TopoDS_Vertex finalVertex = TopExp::LastVertex(edge);
    constexpr double finalTolerance = 1.339747697e-6;
    BRep_Builder builder;
    builder.UpdateVertex(
        finalVertex,
        gp_Pnt(8325.687393942937, 11600.68739260329, -1592.2710917531094),
        finalTolerance
    );
    ASSERT_TRUE(BRepCheck_Analyzer(edge).IsValid());

    const Part::TopoShape original(edge);
    std::stringstream brep;
    original.exportBrep(brep);

    Part::TopoShape restored;
    restored.importBrep(brep);
    EXPECT_TRUE(restored.isValid());

    builder.UpdateVertex(
        finalVertex,
        gp_Pnt(8325.687393952937, 11600.68739260329, -1592.2710917531094),
        finalTolerance
    );
    const BRepCheck_Analyzer invalidAnalyzer(edge);
    ASSERT_FALSE(invalidAnalyzer.IsValid());
    const auto& vertexResult = invalidAnalyzer.Result(finalVertex);
    ASSERT_TRUE(vertexResult->IsStatusOnShape(edge));
    EXPECT_TRUE(vertexResult->StatusOnShape(edge).Contains(BRepCheck_InvalidPointOnCurve));

    const Part::TopoShape invalidOriginal(edge);
    std::stringstream invalidBrep;
    invalidOriginal.exportBrep(invalidBrep);

    Part::TopoShape invalidRestored;
    invalidRestored.importBrep(invalidBrep);
    EXPECT_FALSE(invalidRestored.isValid());
}

// clang-format on
