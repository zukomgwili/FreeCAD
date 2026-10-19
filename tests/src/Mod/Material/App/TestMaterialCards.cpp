// SPDX-License-Identifier: LGPL-2.1-or-later
/***************************************************************************
 *   Copyright (c) 2023 David Carter <dcarter@david.carter.ca>             *
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

#include <gtest/gtest.h>

#include <QDir>
#include <QFile>
#include <QMetaType>
#include <QString>

#include <App/Application.h>
#include <Base/Quantity.h>
#include <Gui/MetaTypes.h>
#include <src/App/InitApplication.h>
#include <src/TempDirectory.h>

#include <Mod/Material/App/MaterialLibrary.h>
#include <Mod/Material/App/MaterialLoader.h>
#include <Mod/Material/App/MaterialManager.h>
#include <Mod/Material/App/MaterialValue.h>
#include <Mod/Material/App/Model.h>
#include <Mod/Material/App/ModelManager.h>
#include <Mod/Material/App/ModelUuids.h>

// clang-format off

class TestMaterialCards : public ::testing::Test {
protected:
    static void SetUpTestSuite() {
        if (App::Application::GetARGC() == 0) {
            tests::initApplication();
        }
    }

    void SetUp() override {
        QString libPath = QString::fromStdString(_tempDir.string());
        _library = std::make_shared<Materials::MaterialLibraryLocal>(QStringLiteral("Testing"),
                        libPath,
                        QStringLiteral(":/icons/preferences-general.svg"),
                        false);
        _modelManager = &(Materials::ModelManager::getManager());
        _materialManager = &(Materials::MaterialManager::getManager());

        _testMaterialUUID = QStringLiteral("c6c64159-19c1-40b5-859c-10561f20f979");
    }

    tests::TempDirectory _tempDir {"TestMaterialCards"};
    Materials::ModelManager* _modelManager;
    Materials::MaterialManager* _materialManager;
    std::shared_ptr<Materials::MaterialLibraryLocal> _library;
    QString _testMaterialUUID;
};

TEST_F(TestMaterialCards, TestCopy)
{
    ASSERT_NE(_modelManager, nullptr);
    ASSERT_TRUE(_library);
    // FAIL() << "Test library " << _library->getDirectoryPath().toStdString() << "\n";

    auto testMaterial = _materialManager->getMaterial(_testMaterialUUID);
    auto newMaterial = std::make_shared<Materials::Material>(*testMaterial);

    EXPECT_EQ(testMaterial->getUUID(), _testMaterialUUID);
    EXPECT_EQ(newMaterial->getUUID(), _testMaterialUUID);

    // Save the material
    _materialManager->saveMaterial(_library,
                      newMaterial,
                      QStringLiteral("/Test Material2.FCMat"),
                      false, // overwrite
                      true,  // saveAsCopy
                      false); // saveInherited
    EXPECT_EQ(newMaterial->getUUID(), _testMaterialUUID);
    EXPECT_EQ(newMaterial->getName(), QStringLiteral("Test Material2"));

    // Save it when it already exists throwing an error
    EXPECT_THROW(_materialManager->saveMaterial(_library,
                      newMaterial,
                      QStringLiteral("/Test Material2.FCMat"),
                      false, // overwrite
                      true,  // saveAsCopy
                      false) // saveInherited
                      , Materials::MaterialExists);
    EXPECT_EQ(newMaterial->getUUID(), _testMaterialUUID);
    EXPECT_EQ(newMaterial->getName(), QStringLiteral("Test Material2"));

    // Overwrite the existing file
    _materialManager->saveMaterial(_library,
                      newMaterial,
                      QStringLiteral("/Test Material2.FCMat"),
                      true,  // overwrite
                      true,  // saveAsCopy
                      false);// saveInherited
    EXPECT_EQ(newMaterial->getUUID(), _testMaterialUUID);
    EXPECT_EQ(newMaterial->getName(), QStringLiteral("Test Material2"));

    // Save to a new file, inheritance mode
    _materialManager->saveMaterial(_library,
                      newMaterial,
                      QStringLiteral("/Test Material3.FCMat"),
                      false,  // overwrite
                      true,  // saveAsCopy
                      true);// saveInherited
    EXPECT_EQ(newMaterial->getUUID(), _testMaterialUUID);
    EXPECT_EQ(newMaterial->getName(), QStringLiteral("Test Material3"));

    // Save to a new file, inheritance mode. no copy
    _materialManager->saveMaterial(_library,
                      newMaterial,
                      QStringLiteral("/Test Material4.FCMat"),
                      false,  // overwrite
                      false,  // saveAsCopy
                      true);// saveInherited
    EXPECT_NE(newMaterial->getUUID(), _testMaterialUUID);
    EXPECT_EQ(newMaterial->getName(), QStringLiteral("Test Material4"));
    QString uuid1 = newMaterial->getUUID();

    // Save to a new file, inheritance mode, testing overwrite, new copy
    _materialManager->saveMaterial(_library,
                      newMaterial,
                      QStringLiteral("/Test Material5.FCMat"),
                      false,  // overwrite
                      true,  // saveAsCopy
                      true);// saveInherited
    EXPECT_EQ(newMaterial->getUUID(), uuid1);
    EXPECT_EQ(newMaterial->getName(), QStringLiteral("Test Material5"));

    _materialManager->saveMaterial(_library,
                      newMaterial,
                      QStringLiteral("/Test Material5.FCMat"),
                      true,  // overwrite
                      true,  // saveAsCopy
                      true);// saveInherited
    EXPECT_EQ(newMaterial->getUUID(), uuid1);
    EXPECT_EQ(newMaterial->getName(), QStringLiteral("Test Material5"));

    // Save to a new file, inheritance mode, testing overwrite as no copy, new copy
    _materialManager->saveMaterial(_library,
                      newMaterial,
                      QStringLiteral("/Test Material6.FCMat"),
                      false,  // overwrite
                      true,  // saveAsCopy
                      true);// saveInherited
    EXPECT_EQ(newMaterial->getUUID(), uuid1);
    EXPECT_EQ(newMaterial->getName(), QStringLiteral("Test Material6"));

    _materialManager->saveMaterial(_library,
                      newMaterial,
                      QStringLiteral("/Test Material6.FCMat"),
                      true,  // overwrite
                      false,  // saveAsCopy
                      true);// saveInherited
    EXPECT_EQ(newMaterial->getUUID(), uuid1);
    EXPECT_EQ(newMaterial->getName(), QStringLiteral("Test Material6"));
}

TEST_F(TestMaterialCards, TestColumns)
{
    ASSERT_NE(_modelManager, nullptr);
    ASSERT_TRUE(_library);

    auto testMaterial = _materialManager->getMaterial(_testMaterialUUID);

    EXPECT_TRUE(testMaterial->hasPhysicalProperty(QStringLiteral("TestArray2D")));
    auto array2d = testMaterial->getPhysicalProperty(QStringLiteral("TestArray2D"))->getMaterialValue();
    EXPECT_TRUE(array2d);
    EXPECT_EQ(dynamic_cast<Materials::Array2D &>(*array2d).columns(), 2);

    EXPECT_TRUE(testMaterial->hasPhysicalProperty(QStringLiteral("TestArray2D3Column")));
    auto array2d3Column = testMaterial->getPhysicalProperty(QStringLiteral("TestArray2D3Column"))->getMaterialValue();
    EXPECT_TRUE(array2d3Column);
    EXPECT_EQ(dynamic_cast<Materials::Array2D &>(*array2d3Column).columns(), 3);

    EXPECT_TRUE(testMaterial->hasPhysicalProperty(QStringLiteral("TestArray3D")));
    auto array3d = testMaterial->getPhysicalProperty(QStringLiteral("TestArray3D"))->getMaterialValue();
    EXPECT_TRUE(array3d);
    EXPECT_EQ(dynamic_cast<Materials::Array3D &>(*array3d).columns(), 2);
}

// clang-format on

TEST_F(TestMaterialCards, RejectedArrayOverwritePreservesExistingCardAndMaterial)
{
    const QString path = QStringLiteral("/Preserved.FCMat");
    const QString local = QString::fromStdString(_tempDir.string()) + path;
    const QByteArray original("Existing material card must survive a rejected overwrite\n");
    {
        QFile file(local);
        ASSERT_TRUE(file.open(QIODevice::WriteOnly));
        ASSERT_EQ(file.write(original), original.size());
    }
    auto material = std::make_shared<Materials::Material>();
    material->setName(QStringLiteral("Unsaved source name"));
    material->addPhysical(QStringLiteral("34d0583d-f999-49ba-99e6-aa40bd5c3a6b"));
    auto array = std::dynamic_pointer_cast<Materials::Array2D>(
        material->getPhysicalProperty(QStringLiteral("TestArray2D"))->getMaterialValue()
    );
    ASSERT_NE(array, nullptr);
    array->setRows(1);
    array->setValue(0, 0, QVariant::fromValue(QByteArray("unsupported native cell")));
    const auto uuid = material->getUUID();
    const auto name = material->getName();
    EXPECT_THROW(_library->saveMaterial(material, path, true, false, false), Materials::InvalidProperty);
    QFile file(local);
    ASSERT_TRUE(file.open(QIODevice::ReadOnly));
    EXPECT_EQ(file.readAll(), original);
    EXPECT_EQ(material->getUUID(), uuid);
    EXPECT_EQ(material->getName(), name);
    EXPECT_THROW(_library->getMaterialByPath(path), Materials::MaterialNotFound);
}

TEST_F(TestMaterialCards, RejectedNewArraySaveLeavesNoPartialCard)
{
    auto material = std::make_shared<Materials::Material>();
    material->addPhysical(QStringLiteral("34d0583d-f999-49ba-99e6-aa40bd5c3a6b"));
    auto array = std::dynamic_pointer_cast<Materials::Array2D>(
        material->getPhysicalProperty(QStringLiteral("TestArray2D"))->getMaterialValue()
    );
    ASSERT_NE(array, nullptr);
    array->setRows(1);
    array->setValue(0, 0, QVariant::fromValue(QByteArray("unsupported native cell")));
    const auto uuid = material->getUUID();
    const QString path = QStringLiteral("/Rejected.FCMat");
    EXPECT_THROW(_library->saveMaterial(material, path, false, false, false), Materials::InvalidProperty);
    EXPECT_FALSE(QFile::exists(QString::fromStdString(_tempDir.string()) + path));
    EXPECT_EQ(material->getUUID(), uuid);
    EXPECT_THROW(_library->getMaterialByPath(path), Materials::MaterialNotFound);
}

TEST_F(TestMaterialCards, FailedMaterialDirectoryCreationDoesNotPublishMaterial)
{
    const QString blocker = QString::fromStdString(_tempDir.string()) + QStringLiteral("/blocked");
    const QByteArray original("A file cannot be used as the destination directory\n");
    {
        QFile file(blocker);
        ASSERT_TRUE(file.open(QIODevice::WriteOnly));
        ASSERT_EQ(file.write(original), original.size());
    }
    auto material = std::make_shared<Materials::Material>();
    material->setName(QStringLiteral("Not saved"));
    const auto uuid = material->getUUID();
    const QString path = QStringLiteral("/blocked/New.FCMat");
    EXPECT_THROW(_library->saveMaterial(material, path, false, false, false), Materials::CreationError);
    EXPECT_EQ(material->getUUID(), uuid);
    EXPECT_EQ(material->getName(), QStringLiteral("Not saved"));
    EXPECT_THROW(_library->getMaterialByPath(path), Materials::MaterialNotFound);
    QFile file(blocker);
    ASSERT_TRUE(file.open(QIODevice::ReadOnly));
    EXPECT_EQ(file.readAll(), original);
}

TEST_F(TestMaterialCards, NullNativeArrayRowCannotTruncateExistingCard)
{
    const QString path = QStringLiteral("/NullRow.FCMat");
    const QString local = QString::fromStdString(_tempDir.string()) + path;
    const QByteArray original("Previous material remains intact after an invalid native row\n");
    {
        QFile file(local);
        ASSERT_TRUE(file.open(QIODevice::WriteOnly));
        ASSERT_EQ(file.write(original), original.size());
    }
    auto material = std::make_shared<Materials::Material>();
    material->addPhysical(QStringLiteral("34d0583d-f999-49ba-99e6-aa40bd5c3a6b"));
    auto array = std::dynamic_pointer_cast<Materials::Array2D>(
        material->getPhysicalProperty(QStringLiteral("TestArray2D"))->getMaterialValue()
    );
    ASSERT_NE(array, nullptr);
    array->addRow(nullptr);
    const auto uuid = material->getUUID();
    EXPECT_THROW(_library->saveMaterial(material, path, true, false, false), Materials::InvalidProperty);
    QFile file(local);
    ASSERT_TRUE(file.open(QIODevice::ReadOnly));
    EXPECT_EQ(file.readAll(), original);
    EXPECT_EQ(material->getUUID(), uuid);
    EXPECT_THROW(_library->getMaterialByPath(path), Materials::MaterialNotFound);
}

TEST_F(TestMaterialCards, SuccessfulArraySaveKeepsHeldPropertiesLiveAndPublishesMetadata)
{
    auto material = std::make_shared<Materials::Material>();
    material->setName(QStringLiteral("Caller-owned name"));
    material->setFilename(QStringLiteral("Caller-owned filename.FCMat"));
    material->setParentUUID(_testMaterialUUID);
    material->setOldFormat(true);
    material->addPhysical(Materials::ModelUUIDs::ModelUUID_Test_Model);
    material->addAppearance(Materials::ModelUUIDs::ModelUUID_Rendering_Basic);
    const auto property = material->getPhysicalProperty(QStringLiteral("TestArray2D"));
    const auto appearance = material->getAppearanceProperty(QStringLiteral("Shininess"));
    const auto array = std::dynamic_pointer_cast<Materials::Array2D>(property->getMaterialValue());
    ASSERT_NE(array, nullptr);
    array->setRows(1);
    const double precise = 0.12345678901234567;
    const Base::Quantity quantity(123.45678901234567, Base::Unit::Length);
    array->setValue(0, 0, QVariant::fromValue(precise));
    array->setValue(0, 1, QVariant::fromValue(quantity));
    appearance->setValue(QVariant::fromValue(42.125F));
    material->resetEditState();
    const auto originalUUID = material->getUUID();

    const auto checkLiveAliases = [&] {
        EXPECT_EQ(material->getPhysicalProperty(QStringLiteral("TestArray2D")), property);
        EXPECT_EQ(
            material->getPhysicalProperty(QStringLiteral("TestArray2D"))->getMaterialValue(),
            array
        );
        EXPECT_EQ(material->getAppearanceProperty(QStringLiteral("Shininess")), appearance);
    };
    const auto readSavedArray = [&](const QString& path) {
        QFile file(QString::fromStdString(_tempDir.string()) + path);
        if (!file.open(QIODevice::ReadOnly)) {
            throw Materials::MaterialReadError("Could not open saved test material");
        }
        auto yaml = YAML::Load(file.readAll().toStdString());
        EXPECT_EQ(
            QString::fromStdString(yaml["General"]["UUID"].as<std::string>()),
            material->getUUID()
        );
        auto entry = Materials::MaterialLoader::getMaterialFromYAML(_library, yaml, path);
        auto materials = std::make_shared<std::map<QString, std::shared_ptr<Materials::Material>>>();
        entry->addToTree(materials);
        return std::dynamic_pointer_cast<Materials::Array2D>(
            materials->at(material->getUUID())
                ->getPhysicalProperty(QStringLiteral("TestArray2D"))
                ->getMaterialValue()
        );
    };

    const QString copyPath = QStringLiteral("/LiveArrayCopy.FCMat");
    _materialManager->saveMaterial(_library, material, copyPath, false, true, false);
    EXPECT_EQ(material->getUUID(), originalUUID);
    EXPECT_EQ(material->getName(), QStringLiteral("LiveArrayCopy"));
    EXPECT_EQ(material->getDirectory(), QStringLiteral("LiveArrayCopy.FCMat"));
    EXPECT_EQ(material->getLibrary(), _library);
    EXPECT_EQ(material->getParentUUID(), _testMaterialUUID);
    EXPECT_EQ(material->getFilename(), QStringLiteral("Caller-owned filename.FCMat"));
    EXPECT_EQ(material->getEditState(), Materials::Material::ModelEdit_Extend);
    EXPECT_FALSE(material->isOldFormat());
    checkLiveAliases();
    auto restored = readSavedArray(copyPath);
    ASSERT_NE(restored, nullptr);
    EXPECT_EQ(restored->getValue(0, 0).userType(), QMetaType::Double);
    EXPECT_EQ(restored->getValue(0, 0).toDouble(), precise);
    EXPECT_EQ(restored->getValue(0, 1).value<Base::Quantity>(), quantity);

    // A native editor can retain these shared objects while saving its material.
    // Subsequent edits must still reach the material, not detached pre-save copies.
    const double edited = 0.31415926535897931;
    array->setValue(0, 0, QVariant::fromValue(edited));
    appearance->setValue(QVariant::fromValue(17.75F));
    EXPECT_EQ(
        material->getPhysicalProperty(QStringLiteral("TestArray2D"))->getMaterialValue()->getType(),
        Materials::MaterialValue::Array2D
    );
    EXPECT_EQ(
        std::dynamic_pointer_cast<Materials::Array2D>(
            material->getPhysicalProperty(QStringLiteral("TestArray2D"))->getMaterialValue()
        )
            ->getValue(0, 0)
            .toDouble(),
        edited
    );
    EXPECT_EQ(material->getAppearanceProperty(QStringLiteral("Shininess"))->getValue().toFloat(), 17.75F);

    const QString newPath = QStringLiteral("/LiveArrayNew.FCMat");
    _materialManager->saveMaterial(_library, material, newPath, false, false, false);
    EXPECT_NE(material->getUUID(), originalUUID);
    EXPECT_EQ(material->getName(), QStringLiteral("LiveArrayNew"));
    EXPECT_EQ(material->getDirectory(), QStringLiteral("LiveArrayNew.FCMat"));
    EXPECT_EQ(material->getParentUUID(), _testMaterialUUID);
    checkLiveAliases();
    restored = readSavedArray(newPath);
    ASSERT_NE(restored, nullptr);
    EXPECT_EQ(restored->getValue(0, 0).toDouble(), edited);
    EXPECT_EQ(restored->getValue(0, 1).value<Base::Quantity>(), quantity);

    const auto newUUID = material->getUUID();
    material->setParentUUID(newUUID);
    material->setOldFormat(true);
    _materialManager
        ->saveMaterial(_library, material, QStringLiteral("/NoSelfParent.FCMat"), false, true, true);
    EXPECT_EQ(material->getUUID(), newUUID);
    EXPECT_TRUE(material->getParentUUID().isEmpty());
    EXPECT_FALSE(material->isOldFormat());
    checkLiveAliases();
}
