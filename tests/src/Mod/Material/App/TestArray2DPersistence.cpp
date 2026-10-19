// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <bit>
#include <cstdint>
#include <limits>
#include <memory>

#include <QVariant>
#include <QTextStream>

#include <App/Application.h>
#include <Base/Quantity.h>
#include <Gui/MetaTypes.h>
#include <src/App/InitApplication.h>
#include <src/TempDirectory.h>

#include <Mod/Material/App/MaterialLibrary.h>
#include <Mod/Material/App/MaterialLoader.h>
#include <Mod/Material/App/MaterialManager.h>
#include <Mod/Material/App/Exceptions.h>
#include <Mod/Material/App/MaterialValue.h>
#include <Mod/Material/App/ModelManager.h>

namespace
{

QVariant typedNull(int type)
{
#if QT_VERSION >= QT_VERSION_CHECK(6, 0, 0)
    return QVariant(QMetaType(type), nullptr);
#else
    return QVariant(type, nullptr);
#endif
}

class TestArray2DPersistence: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        if (App::Application::GetARGC() == 0) {
            tests::initApplication();
        }
        Materials::ModelManager::getManager();
    }

    std::shared_ptr<Materials::Array2D> read(const QString& arrayYAML)
    {
        const QString uuid = QStringLiteral("870006bf-763a-483b-a507-b8d0ad4da75a");
        const QString yaml = QStringLiteral(
                                 "General:\n  UUID: '%1'\nModels:\n  Test:\n"
                                 "    UUID: '34d0583d-f999-49ba-99e6-aa40bd5c3a6b'\n"
                                 "    TestArray2D: "
                             )
                                 .arg(uuid)
            + arrayYAML;
        return readCard(yaml);
    }

    std::shared_ptr<Materials::Material> readMaterialCard(const QString& yaml)
    {
        auto document = YAML::Load(yaml.toStdString());
        const auto uuid = QString::fromStdString(document["General"]["UUID"].as<std::string>());
        auto library = std::make_shared<Materials::MaterialLibraryLocal>(
            QStringLiteral("Array persistence test"),
            QString::fromStdString(_directory.string()),
            QStringLiteral(":/icons/preferences-general.svg"),
            false
        );
        auto entry = Materials::MaterialLoader::getMaterialFromYAML(
            library,
            document,
            QStringLiteral("/ArrayPersistence.FCMat")
        );
        auto materials = std::make_shared<std::map<QString, std::shared_ptr<Materials::Material>>>();
        entry->addToTree(materials);
        const auto material = materials->at(uuid);
        if (!material->getParentUUID().isEmpty()) {
            const auto parent = Materials::MaterialManager::getManager().getMaterial(
                material->getParentUUID()
            );
            (*materials)[parent->getUUID()] = parent;
            Materials::MaterialLoader::dereference(materials, material);
        }
        return material;
    }

    std::shared_ptr<Materials::Array2D> readCard(const QString& yaml, bool appearance = false)
    {
        const auto material = readMaterialCard(yaml);
        const auto property = appearance
            ? material->getAppearanceProperty(QStringLiteral("TestArray2D"))
            : material->getPhysicalProperty(QStringLiteral("TestArray2D"));
        return std::dynamic_pointer_cast<Materials::Array2D>(property->getMaterialValue());
    }

    std::shared_ptr<Materials::Array2D> roundTrip(const Materials::Array2D& array, bool appearance = false)
    {
        Materials::Material material;
        const auto value = std::static_pointer_cast<Materials::MaterialValue>(
            std::make_shared<Materials::Array2D>(array)
        );
        if (appearance) {
            material.addAppearance(QStringLiteral("34d0583d-f999-49ba-99e6-aa40bd5c3a6b"));
            material.setAppearanceValue(QStringLiteral("TestArray2D"), value);
        }
        else {
            material.addPhysical(QStringLiteral("34d0583d-f999-49ba-99e6-aa40bd5c3a6b"));
            material.setPhysicalValue(QStringLiteral("TestArray2D"), value);
        }
        QString yaml;
        QTextStream stream(&yaml);
        material.save(stream, true, false, false);
        return readCard(yaml, appearance);
    }

    tests::TempDirectory _directory {"TestArray2DPersistence"};
};

TEST_F(TestArray2DPersistence, MaterialCardRoundTripRetainsNativeQuantityPrecisionAndUnits)
{
    Materials::Array2D original;
    original.setColumns(2);
    original.setRows(1);
    const Base::Quantity precise(123.45678901234567, Base::Unit::Length);
    const Base::Quantity tiny(1.2345678901234567e-123, Base::Unit::Pressure);
    original.setValue(0, 0, QVariant::fromValue(precise));
    original.setValue(0, 1, QVariant::fromValue(tiny));

    std::shared_ptr<Materials::Array2D> restored;
    try {
        restored = roundTrip(original);
    }
    catch (const Base::Exception& error) {
        FAIL() << error.what();
    }
    ASSERT_NE(restored, nullptr);
    ASSERT_EQ(restored->rows(), 1);
    ASSERT_EQ(restored->columns(), 2);
    const auto restoredPrecise = restored->getValue(0, 0).value<Base::Quantity>();
    const auto restoredTiny = restored->getValue(0, 1).value<Base::Quantity>();
    EXPECT_EQ(restoredPrecise.getValue(), precise.getValue());
    EXPECT_EQ(restoredPrecise.getUnit(), precise.getUnit());
    EXPECT_EQ(restoredTiny.getValue(), tiny.getValue());
    EXPECT_EQ(restoredTiny.getUnit(), tiny.getUnit());
}

TEST_F(TestArray2DPersistence, MaterialCardRoundTripRetainsEverySupportedNativeCellType)
{
    const QString text = QString::fromUtf8("Grüße λ\n\"quoted\"\\") + QChar(u'\0')
        + QStringLiteral("after") + QChar(0xd800);
    const QList<QVariant> cells {
        QVariant(),
        typedNull(QMetaType::Int),
        typedNull(QMetaType::Double),
        typedNull(qMetaTypeId<Base::Quantity>()),
        typedNull(QMetaType::QString),
        QVariant::fromValue(Base::Quantity(-0.0, Base::Unit(1, -2, 3, -4, 5, -6, 7, -8))),
        QVariant::fromValue(0.123456789F),
        QVariant::fromValue(-0.0F),
        QVariant::fromValue(std::bit_cast<float>(std::uint32_t(0x7fc0abcd))),
        QVariant::fromValue(std::numeric_limits<float>::infinity()),
        QVariant::fromValue(0.12345678901234567),
        QVariant::fromValue(-0.0),
        QVariant::fromValue(std::numeric_limits<double>::denorm_min()),
        QVariant::fromValue(std::numeric_limits<double>::max()),
        QVariant::fromValue(-std::numeric_limits<double>::infinity()),
        QVariant::fromValue(std::bit_cast<double>(std::uint64_t(0x7ff800000000cafe))),
        QVariant::fromValue(static_cast<char>(-12)),
        QVariant::fromValue(std::numeric_limits<signed char>::min()),
        QVariant::fromValue(std::numeric_limits<unsigned char>::max()),
        QVariant::fromValue(std::numeric_limits<short>::min()),
        QVariant::fromValue(std::numeric_limits<unsigned short>::max()),
        QVariant::fromValue(std::numeric_limits<int>::min()),
        QVariant::fromValue(std::numeric_limits<unsigned int>::max()),
        QVariant::fromValue(std::numeric_limits<long>::min()),
        QVariant::fromValue(std::numeric_limits<unsigned long>::max()),
        QVariant::fromValue(std::numeric_limits<qlonglong>::min()),
        QVariant::fromValue(std::numeric_limits<qulonglong>::max()),
        QVariant::fromValue(true),
        QVariant::fromValue(false),
        QVariant::fromValue(text),
        QVariant::fromValue(QStringLiteral("")),
        QVariant::fromValue(QString())
    };
    Materials::Array2D original;
    original.setColumns(cells.size());
    original.addRow(std::make_shared<QList<QVariant>>(cells));

    std::shared_ptr<Materials::Array2D> restored;
    try {
        restored = roundTrip(original);
    }
    catch (const Base::Exception& error) {
        FAIL() << error.what();
    }
    ASSERT_NE(restored, nullptr);
    ASSERT_EQ(restored->rows(), 1);
    ASSERT_EQ(restored->columns(), cells.size());
    for (int column = 0; column < cells.size(); ++column) {
        SCOPED_TRACE(column);
        const auto expected = cells[column];
        const auto actual = restored->getValue(0, column);
        ASSERT_EQ(actual.userType(), expected.userType());
        EXPECT_EQ(actual.isNull(), expected.isNull());
        if (expected.isNull()) {
            continue;
        }
        if (expected.userType() == QMetaType::Float) {
            EXPECT_EQ(
                std::bit_cast<std::uint32_t>(actual.value<float>()),
                std::bit_cast<std::uint32_t>(expected.value<float>())
            );
        }
        else if (expected.userType() == QMetaType::Double) {
            EXPECT_EQ(
                std::bit_cast<std::uint64_t>(actual.value<double>()),
                std::bit_cast<std::uint64_t>(expected.value<double>())
            );
        }
        else if (expected.userType() == qMetaTypeId<Base::Quantity>()) {
            EXPECT_EQ(
                std::bit_cast<std::uint64_t>(actual.value<Base::Quantity>().getValue()),
                std::bit_cast<std::uint64_t>(expected.value<Base::Quantity>().getValue())
            );
            EXPECT_EQ(
                actual.value<Base::Quantity>().getUnit(),
                expected.value<Base::Quantity>().getUnit()
            );
        }
        else {
            EXPECT_EQ(actual, expected);
            if (expected.userType() == QMetaType::QString) {
                EXPECT_EQ(actual.toString().isNull(), expected.toString().isNull());
            }
        }
    }
}

TEST_F(TestArray2DPersistence, MaterialCardSaveRetainsZeroSizedDimensions)
{
    for (const bool appearance : {false, true}) {
        SCOPED_TRACE(appearance);
        for (const auto shape : {std::pair(0, 7), std::pair(3, 0), std::pair(0, 0)}) {
            SCOPED_TRACE(shape.first);
            SCOPED_TRACE(shape.second);
            Materials::Array2D original;
            original.setColumns(shape.second);
            original.setRows(shape.first);
            const auto restored = roundTrip(original, appearance);
            ASSERT_NE(restored, nullptr);
            EXPECT_EQ(restored->rows(), shape.first);
            EXPECT_EQ(restored->columns(), shape.second);
        }
    }
}

TEST_F(TestArray2DPersistence, InheritedMaterialCardSaveRetainsArrayEdits)
{
    const auto parent = Materials::MaterialManager::getManager().getMaterial(
        QStringLiteral("c6c64159-19c1-40b5-859c-10561f20f979")
    );
    Materials::Material child(*parent);
    child.newUuid();
    child.setParentUUID(parent->getUUID());
    auto array = std::dynamic_pointer_cast<Materials::Array2D>(
        child.getPhysicalProperty(QStringLiteral("TestArray2D"))->getMaterialValue()
    );
    ASSERT_NE(array, nullptr);
    ASSERT_GT(array->rows(), 0);
    array->setValue(0, 0, QVariant::fromValue(false));
    QString yaml;
    QTextStream stream(&yaml);
    child.save(stream, true, false, true);
    const auto document = YAML::Load(yaml.toStdString());
    ASSERT_TRUE(document["Inherits"]);
    ASSERT_EQ(child.getParentUUID(), parent->getUUID());
    ASSERT_TRUE(
        document["Models"] && document["Models"]["Test Model"]
        && document["Models"]["Test Model"]["TestArray2D"]
    );
    const auto restored = readCard(yaml);
    ASSERT_NE(restored, nullptr);
    EXPECT_EQ(restored->rows(), array->rows());
    EXPECT_EQ(restored->getValue(0, 0).userType(), QMetaType::Bool);
    EXPECT_FALSE(restored->getValue(0, 0).toBool());
}

TEST_F(TestArray2DPersistence, InheritedMaterialCardLoadsAnUnchangedArrayWithoutSharingIt)
{
    const auto parent = Materials::MaterialManager::getManager().getMaterial(
        QStringLiteral("c6c64159-19c1-40b5-859c-10561f20f979")
    );
    const auto parentArray = std::dynamic_pointer_cast<Materials::Array2D>(
        parent->getPhysicalProperty(QStringLiteral("TestArray2D"))->getMaterialValue()
    );
    Materials::Material child(*parent);
    child.newUuid();
    child.setParentUUID(parent->getUUID());
    QString yaml;
    QTextStream stream(&yaml);
    child.save(stream, true, false, true);
    const auto document = YAML::Load(yaml.toStdString());
    ASSERT_TRUE(document["Inherits"]);
    ASSERT_FALSE(document["Models"]);
    const auto restored = readCard(yaml);
    ASSERT_NE(restored, nullptr);
    ASSERT_EQ(restored->rows(), parentArray->rows());
    ASSERT_GT(restored->rows(), 0);
    EXPECT_EQ(*restored, *parentArray);
    const auto parentCell = parentArray->getValue(0, 0);
    restored->setValue(0, 0, QVariant::fromValue(false));
    EXPECT_EQ(parentArray->getValue(0, 0), parentCell);
}

TEST_F(TestArray2DPersistence, InheritedMaterialCardRetainsAnExplicitEmptyOverride)
{
    const auto parent = Materials::MaterialManager::getManager().getMaterial(
        QStringLiteral("c6c64159-19c1-40b5-859c-10561f20f979")
    );
    Materials::Material child(*parent);
    child.newUuid();
    child.setParentUUID(parent->getUUID());
    auto empty = std::make_shared<Materials::Array2D>();
    empty->setColumns(7);
    child.setPhysicalValue(
        QStringLiteral("TestArray2D"),
        std::static_pointer_cast<Materials::MaterialValue>(empty)
    );
    QString yaml;
    QTextStream stream(&yaml);
    child.save(stream, true, false, true);
    const auto document = YAML::Load(yaml.toStdString());
    ASSERT_TRUE(document["Inherits"]);
    ASSERT_TRUE(document["Models"]["Test Model"]["TestArray2D"]);
    const auto restored = readCard(yaml);
    ASSERT_NE(restored, nullptr);
    EXPECT_EQ(restored->rows(), 0);
    EXPECT_EQ(restored->columns(), 7);
}

TEST_F(TestArray2DPersistence, UnresolvedInheritedArrayDefaultsAreNotSavedAsExplicitClears)
{
    const auto parent = Materials::MaterialManager::getManager().getMaterial(
        QStringLiteral("c6c64159-19c1-40b5-859c-10561f20f979")
    );
    Materials::Material child;
    child.addPhysical(QStringLiteral("34d0583d-f999-49ba-99e6-aa40bd5c3a6b"));
    child.setParentUUID(parent->getUUID());
    QString yaml;
    QTextStream stream(&yaml);
    child.save(stream, true, false, true);
    const auto document = YAML::Load(yaml.toStdString());
    ASSERT_TRUE(document["Inherits"]);
    EXPECT_FALSE(document["Models"]["Test Model"]["TestArray2D"]);
    const auto restored = readCard(yaml);
    ASSERT_NE(restored, nullptr);
    EXPECT_EQ(restored->rows(), 3);
    EXPECT_EQ(restored->columns(), 2);
}

TEST_F(TestArray2DPersistence, MutableInheritedRowsRemainPersistable)
{
    const auto parent = Materials::MaterialManager::getManager().getMaterial(
        QStringLiteral("c6c64159-19c1-40b5-859c-10561f20f979")
    );
    Materials::Material child(*parent);
    child.newUuid();
    child.setParentUUID(parent->getUUID());
    QString initial;
    QTextStream initialStream(&initial);
    child.save(initialStream, true, false, true);
    const auto loaded = readMaterialCard(initial);
    const auto array = std::dynamic_pointer_cast<Materials::Array2D>(
        loaded->getPhysicalProperty(QStringLiteral("TestArray2D"))->getMaterialValue()
    );
    ASSERT_NE(array, nullptr);
    ASSERT_GT(array->rows(), 0);
    array->getRow(0)->replace(0, QVariant::fromValue(false));
    QString edited;
    QTextStream editedStream(&edited);
    loaded->save(editedStream, true, false, true);
    const auto document = YAML::Load(edited.toStdString());
    ASSERT_TRUE(document["Models"]["Test Model"]["TestArray2D"]);
    const auto restored = readCard(edited);
    EXPECT_EQ(restored->getValue(0, 0).userType(), QMetaType::Bool);
    EXPECT_FALSE(restored->getValue(0, 0).toBool());
}

TEST_F(TestArray2DPersistence, InheritedArrayTypeMismatchesAreRejected)
{
    const auto parent = Materials::MaterialManager::getManager().getMaterial(
        QStringLiteral("c6c64159-19c1-40b5-859c-10561f20f979")
    );
    auto child = std::make_shared<Materials::Material>();
    child->addPhysical(QStringLiteral("34d0583d-f999-49ba-99e6-aa40bd5c3a6b"));
    child->setParentUUID(parent->getUUID());
    child->getPhysicalProperty(QStringLiteral("TestArray2D"))
        ->setValue(std::make_shared<Materials::MaterialValue>(Materials::MaterialValue::String));
    auto materials = std::make_shared<std::map<QString, std::shared_ptr<Materials::Material>>>();
    (*materials)[child->getUUID()] = child;
    (*materials)[parent->getUUID()] = parent;
    EXPECT_THROW(Materials::MaterialLoader::dereference(materials, child), Materials::MaterialReadError);
}

TEST_F(TestArray2DPersistence, MalformedTypedDocumentsAreRejected)
{
    for (const auto& yaml :
         {"{Format: FreeCAD.Array2D, Version: 1, Columns: 0, Rows: []}",
          "[[], [], {Format: FreeCAD.Array2D, Version: 1, Columns: 0, Rows: []}]",
          "[{Format: FreeCAD.Array2D, Version: 2, Columns: 0, Rows: []}]",
          "[{Format: FreeCAD.Array2D, Version: 1, Columns: -1, Rows: []}]",
          "[{Format: FreeCAD.Array2D, Version: 1, Columns: 1, Rows: [[]]}]",
          "[{Format: FreeCAD.Array2D, Version: 1, Columns: 1, Rows: [[{Type: Unknown, Null: "
          "false}]]}]",
          "[{Format: FreeCAD.Array2D, Version: 1, Columns: 1, Rows: [[{Type: UInt, Null: false, "
          "Bits: 32, Value: '-1'}]]}]",
          "[{Format: FreeCAD.Array2D, Version: 1, Columns: 1, Rows: [[{Type: Int, Null: false, "
          "Bits: 32, Value: '2147483648'}]]}]",
          "[{Format: FreeCAD.Array2D, Version: 1, Columns: 1, Rows: [[{Type: Double, Null: false, "
          "Bits: 64, Value: '000000000000000g'}]]}]",
          "[{Format: FreeCAD.Array2D, Version: 1, Columns: 1, Rows: [[{Type: QString, Null: false, "
          "StringNull: false, UTF16: 'abc'}]]}]",
          "[{Format: FreeCAD.Array2D, Version: 1, Columns: 1, Rows: [[{Type: Quantity, Null: "
          "false, Value: '3ff0000000000000', Unit: [8,0,0,0,0,0,0,0]}]]}]"}) {
        SCOPED_TRACE(yaml);
        EXPECT_THROW(read(QString::fromUtf8(yaml)), Materials::MaterialReadError);
    }
}

TEST_F(TestArray2DPersistence, LegacyQuantityStringCardsRemainReadable)
{
    for (const auto& yaml : {"[[['1.25 mm', '3.5 kg']]]", "[ignored, [['1.25 mm', '3.5 kg']]]"}) {
        const auto restored = read(QString::fromUtf8(yaml));
        ASSERT_NE(restored, nullptr);
        ASSERT_EQ(restored->rows(), 1);
        ASSERT_EQ(restored->columns(), 2);
        EXPECT_EQ(
            restored->getValue(0, 0).value<Base::Quantity>(),
            Base::Quantity(1.25, Base::Unit::Length)
        );
        EXPECT_EQ(
            restored->getValue(0, 1).value<Base::Quantity>(),
            Base::Quantity(3.5, Base::Unit::Mass)
        );
    }
    for (const auto& yaml : {"null", "[]"}) {
        const auto restored = read(QString::fromUtf8(yaml));
        ASSERT_NE(restored, nullptr);
        EXPECT_EQ(restored->rows(), 0);
        EXPECT_EQ(restored->columns(), 2);
    }
}

TEST_F(TestArray2DPersistence, UnsupportedNativeValuesAndMalformedRowsAreNotSaved)
{
    for (const auto& cell :
         {QVariant::fromValue(QByteArray("not a material cell")), typedNull(QMetaType::QByteArray)}) {
        Materials::Array2D array;
        array.setColumns(1);
        array.setRows(1);
        array.setValue(0, 0, cell);
        EXPECT_THROW(roundTrip(array), Materials::InvalidProperty);
    }
    Materials::Array2D negative;
    negative.setColumns(-1);
    EXPECT_THROW(roundTrip(negative), Materials::InvalidProperty);
    Materials::Array2D ragged;
    ragged.setColumns(2);
    ragged.addRow(std::make_shared<QList<QVariant>>());
    EXPECT_THROW(roundTrip(ragged), Materials::InvalidProperty);
    Materials::Array2D nullRow;
    nullRow.setColumns(1);
    nullRow.addRow(nullptr);
    EXPECT_THROW(roundTrip(nullRow), Materials::InvalidProperty);
}

}  // namespace
