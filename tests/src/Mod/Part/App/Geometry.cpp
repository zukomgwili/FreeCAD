// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <cmath>

#include <boost/core/ignore_unused.hpp>
#include <Geom_BSplineSurface.hxx>
#include <Geom_ConicalSurface.hxx>
#include <Geom_CylindricalSurface.hxx>
#include <Geom_SphericalSurface.hxx>
#include <Geom_ToroidalSurface.hxx>
#include <NCollection_Array1.hxx>
#include <NCollection_Array2.hxx>
#include <gp_Ax3.hxx>
#include <gp_Cone.hxx>
#include <gp_Cylinder.hxx>
#include <gp_Dir.hxx>
#include <gp_Pln.hxx>
#include <gp_Pnt.hxx>
#include <gp_Sphere.hxx>
#include <gp_Torus.hxx>

#include "Mod/Part/App/Geometry.h"
#include <src/App/InitApplication.h>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include "PartTestHelpers.h"
#include "App/MappedElement.h"

// using namespace Part;
// using namespace PartTestHelpers;

class GeometryTest: public ::testing::Test, public PartTestHelpers::PartTestHelperClass
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }

    void SetUp() override
    {
        createTestDoc();
    }

    void TearDown() override
    {}
};

namespace
{

Part::GeomBSplineSurface makeBSplineSurface(
    const std::vector<double>& uKnots,
    const std::vector<double>& vKnots,
    const std::vector<int>& uMultiplicities,
    const std::vector<int>& vMultiplicities,
    int uDegree,
    int vDegree
)
{
    int uPoleCount = -uDegree - 1;
    for (int multiplicity : uMultiplicities) {
        uPoleCount += multiplicity;
    }
    int vPoleCount = -vDegree - 1;
    for (int multiplicity : vMultiplicities) {
        vPoleCount += multiplicity;
    }

    NCollection_Array2<gp_Pnt> poles(1, uPoleCount, 1, vPoleCount);
    for (int u = poles.LowerRow(); u <= poles.UpperRow(); ++u) {
        for (int v = poles.LowerCol(); v <= poles.UpperCol(); ++v) {
            poles(u, v) = gp_Pnt(u - 1, v - 1, u == 2 && v == 2 ? 1.0 : 0.0);
        }
    }

    NCollection_Array1<double> uKnotArray(1, uKnots.size());
    NCollection_Array1<int> uMultiplicityArray(1, uMultiplicities.size());
    for (int i = uKnotArray.Lower(); i <= uKnotArray.Upper(); ++i) {
        uKnotArray(i) = uKnots.at(i - 1);
        uMultiplicityArray(i) = uMultiplicities.at(i - 1);
    }

    NCollection_Array1<double> vKnotArray(1, vKnots.size());
    NCollection_Array1<int> vMultiplicityArray(1, vMultiplicities.size());
    for (int i = vKnotArray.Lower(); i <= vKnotArray.Upper(); ++i) {
        vKnotArray(i) = vKnots.at(i - 1);
        vMultiplicityArray(i) = vMultiplicities.at(i - 1);
    }

    Handle(Geom_BSplineSurface) surface = new Geom_BSplineSurface(
        poles,
        uKnotArray,
        vKnotArray,
        uMultiplicityArray,
        vMultiplicityArray,
        uDegree,
        vDegree
    );
    return Part::GeomBSplineSurface(surface);
}

Part::GeomBSplineSurface makeLinearBSplineSurface(
    const std::vector<double>& uKnots,
    const std::vector<double>& vKnots
)
{
    std::vector<int> uMultiplicities(uKnots.size(), 1);
    uMultiplicities.front() = 2;
    uMultiplicities.back() = 2;
    std::vector<int> vMultiplicities(vKnots.size(), 1);
    vMultiplicities.front() = 2;
    vMultiplicities.back() = 2;
    return makeBSplineSurface(uKnots, vKnots, uMultiplicities, vMultiplicities, 1, 1);
}

gp_Ax3 makeAxis(double locationX = 0.0, double angle = 0.0)
{
    return {
        gp_Pnt(locationX, 0.0, 0.0),
        gp_Dir(std::sin(angle), 0.0, std::cos(angle)),
        gp_Dir(std::cos(angle), 0.0, -std::sin(angle))
    };
}

Part::GeomPlane makePlane(double locationX = 0.0, double angle = 0.0)
{
    return Part::GeomPlane(gp_Pln(makeAxis(locationX, angle)));
}

Part::GeomCylinder makeCylinder(double radius, double locationX = 0.0, double angle = 0.0)
{
    Handle(Geom_CylindricalSurface) surface = new Geom_CylindricalSurface(
        gp_Cylinder(makeAxis(locationX, angle), radius)
    );
    return Part::GeomCylinder(surface);
}

Part::GeomCone makeCone(double radius, double semiAngle, double locationX = 0.0, double angle = 0.0)
{
    Handle(Geom_ConicalSurface) surface = new Geom_ConicalSurface(
        gp_Cone(makeAxis(locationX, angle), semiAngle, radius)
    );
    return Part::GeomCone(surface);
}

Part::GeomSphere makeSphere(double radius, double locationX = 0.0, double angle = 0.0)
{
    Handle(Geom_SphericalSurface) surface = new Geom_SphericalSurface(
        gp_Sphere(makeAxis(locationX, angle), radius)
    );
    return Part::GeomSphere(surface);
}

Part::GeomToroid makeToroid(
    double majorRadius,
    double minorRadius,
    double locationX = 0.0,
    double angle = 0.0
)
{
    Handle(Geom_ToroidalSurface) surface = new Geom_ToroidalSurface(
        gp_Torus(makeAxis(locationX, angle), majorRadius, minorRadius)
    );
    return Part::GeomToroid(surface);
}

}  // namespace

TEST_F(GeometryTest, elementarySurfaceRuntimeTypesFollowCppInheritance)
{
    Part::GeomPlane plane;
    Part::GeomCylinder cylinder;
    Part::GeomCone cone;
    Part::GeomSphere sphere;
    Part::GeomToroid toroid;

    EXPECT_TRUE(plane.isDerivedFrom<Part::GeomElementarySurface>());
    EXPECT_TRUE(cylinder.isDerivedFrom<Part::GeomElementarySurface>());
    EXPECT_TRUE(cone.isDerivedFrom<Part::GeomElementarySurface>());
    EXPECT_TRUE(sphere.isDerivedFrom<Part::GeomElementarySurface>());
    EXPECT_TRUE(toroid.isDerivedFrom<Part::GeomElementarySurface>());
}

TEST_F(GeometryTest, planeIsSameComparesPlacementWithinTolerance)
{
    constexpr double linearTolerance = 1e-6;
    constexpr double angularTolerance = 1e-6;
    auto plane = makePlane();

    EXPECT_TRUE(plane.isSame(makePlane(), linearTolerance, angularTolerance));
    EXPECT_TRUE(plane.isSame(makePlane(0.5 * linearTolerance), linearTolerance, angularTolerance));
    EXPECT_FALSE(plane.isSame(makePlane(2.0 * linearTolerance), linearTolerance, angularTolerance));
    EXPECT_TRUE(
        plane.isSame(makePlane(0.0, 0.5 * angularTolerance), linearTolerance, angularTolerance)
    );
    EXPECT_FALSE(
        plane.isSame(makePlane(0.0, 2.0 * angularTolerance), linearTolerance, angularTolerance)
    );
}

TEST_F(GeometryTest, cylinderIsSameComparesRadiusAndPlacementWithinTolerance)
{
    constexpr double linearTolerance = 1e-6;
    constexpr double angularTolerance = 1e-6;
    constexpr double radius = 10.0;
    auto cylinder = makeCylinder(radius);

    EXPECT_TRUE(cylinder.isSame(makeCylinder(radius), linearTolerance, angularTolerance));
    EXPECT_TRUE(
        cylinder.isSame(makeCylinder(radius + 0.5 * linearTolerance), linearTolerance, angularTolerance)
    );
    EXPECT_FALSE(
        cylinder.isSame(makeCylinder(radius + 2.0 * linearTolerance), linearTolerance, angularTolerance)
    );
    EXPECT_TRUE(
        cylinder.isSame(makeCylinder(radius, 0.5 * linearTolerance), linearTolerance, angularTolerance)
    );
    EXPECT_FALSE(
        cylinder.isSame(makeCylinder(radius, 2.0 * linearTolerance), linearTolerance, angularTolerance)
    );
}

TEST_F(GeometryTest, coneIsSameComparesParametersAndPlacementWithinTolerance)
{
    constexpr double linearTolerance = 1e-6;
    constexpr double angularTolerance = 1e-6;
    constexpr double radius = 10.0;
    constexpr double semiAngle = 0.25;
    auto cone = makeCone(radius, semiAngle);

    EXPECT_TRUE(cone.isSame(makeCone(radius, semiAngle), linearTolerance, angularTolerance));
    EXPECT_TRUE(
        cone.isSame(makeCone(radius + 0.5 * linearTolerance, semiAngle), linearTolerance, angularTolerance)
    );
    EXPECT_FALSE(
        cone.isSame(makeCone(radius + 2.0 * linearTolerance, semiAngle), linearTolerance, angularTolerance)
    );
    EXPECT_TRUE(
        cone.isSame(makeCone(radius, semiAngle + 0.5 * angularTolerance), linearTolerance, angularTolerance)
    );
    EXPECT_FALSE(
        cone.isSame(makeCone(radius, semiAngle + 2.0 * angularTolerance), linearTolerance, angularTolerance)
    );
    EXPECT_FALSE(
        cone.isSame(makeCone(radius, semiAngle, 2.0 * linearTolerance), linearTolerance, angularTolerance)
    );
}

TEST_F(GeometryTest, sphereIsSameComparesRadiusAndPlacementWithinTolerance)
{
    constexpr double linearTolerance = 1e-6;
    constexpr double angularTolerance = 1e-6;
    constexpr double radius = 10.0;
    auto sphere = makeSphere(radius);

    EXPECT_TRUE(sphere.isSame(makeSphere(radius), linearTolerance, angularTolerance));
    EXPECT_TRUE(
        sphere.isSame(makeSphere(radius + 0.5 * linearTolerance), linearTolerance, angularTolerance)
    );
    EXPECT_FALSE(
        sphere.isSame(makeSphere(radius + 2.0 * linearTolerance), linearTolerance, angularTolerance)
    );
    EXPECT_FALSE(
        sphere.isSame(makeSphere(radius, 2.0 * linearTolerance), linearTolerance, angularTolerance)
    );
}

TEST_F(GeometryTest, toroidIsSameComparesRadiiAndPlacementWithinTolerance)
{
    constexpr double linearTolerance = 1e-6;
    constexpr double angularTolerance = 1e-6;
    constexpr double majorRadius = 10.0;
    constexpr double minorRadius = 2.0;
    auto toroid = makeToroid(majorRadius, minorRadius);

    EXPECT_TRUE(toroid.isSame(makeToroid(majorRadius, minorRadius), linearTolerance, angularTolerance));
    EXPECT_TRUE(toroid.isSame(
        makeToroid(majorRadius + 0.5 * linearTolerance, minorRadius),
        linearTolerance,
        angularTolerance
    ));
    EXPECT_FALSE(toroid.isSame(
        makeToroid(majorRadius + 2.0 * linearTolerance, minorRadius),
        linearTolerance,
        angularTolerance
    ));
    EXPECT_TRUE(toroid.isSame(
        makeToroid(majorRadius, minorRadius + 0.5 * linearTolerance),
        linearTolerance,
        angularTolerance
    ));
    EXPECT_FALSE(toroid.isSame(
        makeToroid(majorRadius, minorRadius + 2.0 * linearTolerance),
        linearTolerance,
        angularTolerance
    ));
    EXPECT_FALSE(toroid.isSame(
        makeToroid(majorRadius, minorRadius, 2.0 * linearTolerance),
        linearTolerance,
        angularTolerance
    ));
}

TEST_F(GeometryTest, bsplineSurfaceIsSameComparesEveryVKnot)
{
    auto first = makeLinearBSplineSurface({0.0, 1.0}, {0.0, 0.5, 1.0});
    auto differentLastVKnot = makeLinearBSplineSurface({0.0, 1.0}, {0.0, 0.5, 2.0});

    EXPECT_FALSE(first.isSame(differentLastVKnot, 1e-8, 1e-12));
}

TEST_F(GeometryTest, bsplineSurfaceIsSameHandlesMoreUKnotsThanVKnots)
{
    auto first = makeLinearBSplineSurface({0.0, 0.5, 1.0}, {0.0, 1.0});
    auto identical = makeLinearBSplineSurface({0.0, 0.5, 1.0}, {0.0, 1.0});

    EXPECT_TRUE(first.isSame(identical, 1e-8, 1e-12));
}

TEST_F(GeometryTest, bsplineSurfaceIsSameComparesEveryVMultiplicity)
{
    auto first = makeBSplineSurface({0.0, 1.0}, {0.0, 1.0, 2.0, 3.0}, {2, 2}, {3, 1, 1, 3}, 1, 2);
    auto differentTrailingVMultiplicities
        = makeBSplineSurface({0.0, 1.0}, {0.0, 1.0, 2.0, 3.0}, {2, 2}, {3, 1, 2, 2}, 1, 2);

    EXPECT_FALSE(first.isSame(differentTrailingVMultiplicities, 1e-8, 1e-12));
}

TEST_F(GeometryTest, testTrimBSpline)
{
    // Arrange
    // create arbitrary B-splines periodic and non-periodic, with arbitrary knots
    // NOTE: Avoid B-spline with typical knots like those ranging from [0,1] or [-1,1]
    int degree = 3;
    std::vector<Base::Vector3d> poles;
    poles.emplace_back(1, 0, 0);
    poles.emplace_back(1, 1, 0);
    poles.emplace_back(1, 0.5, 0);
    poles.emplace_back(0, 1, 0);
    poles.emplace_back(0, 0, 0);
    std::vector<double> weights(5, 1.0);
    std::vector<double> knotsNonPeriodic = {0.0, 1.0, 2.0};
    std::vector<int> multiplicitiesNonPeriodic = {degree + 1, 1, degree + 1};
    Part::GeomBSplineCurve nonPeriodicBSpline1(
        poles,
        weights,
        knotsNonPeriodic,
        multiplicitiesNonPeriodic,
        degree,
        false
    );
    Part::GeomBSplineCurve nonPeriodicBSpline2(
        poles,
        weights,
        knotsNonPeriodic,
        multiplicitiesNonPeriodic,
        degree,
        false
    );
    std::vector<double> knotsPeriodic = {0.0, 0.3, 1.0, 1.5, 1.8, 2.0};
    double period = knotsPeriodic.back() - knotsPeriodic.front();
    std::vector<int> multiplicitiesPeriodic(6, 1);
    Part::GeomBSplineCurve
        periodicBSpline1(poles, weights, knotsPeriodic, multiplicitiesPeriodic, degree, true);
    Part::GeomBSplineCurve
        periodicBSpline2(poles, weights, knotsPeriodic, multiplicitiesPeriodic, degree, true);
    // NOTE: These should be within the knot range, with param1 < param2
    double param1 = 0.5, param2 = 1.4;
    // TODO: Decide what to do if params are outside the range

    // Act
    periodicBSpline1.Trim(param1, param2);
    periodicBSpline2.Trim(param2, param1);
    nonPeriodicBSpline1.Trim(param1, param2);
    // TODO: What happens when a non-periodic B-spline is trimmed this way?
    nonPeriodicBSpline2.Trim(param2, param1);

    // Assert
    EXPECT_DOUBLE_EQ(periodicBSpline1.getFirstParameter(), param1);
    EXPECT_DOUBLE_EQ(periodicBSpline1.getLastParameter(), param2);
    EXPECT_DOUBLE_EQ(periodicBSpline2.getFirstParameter(), param2);
    EXPECT_DOUBLE_EQ(periodicBSpline2.getLastParameter(), param1 + period);
    EXPECT_DOUBLE_EQ(nonPeriodicBSpline1.getFirstParameter(), param1);
    EXPECT_DOUBLE_EQ(nonPeriodicBSpline1.getLastParameter(), param2);
}
