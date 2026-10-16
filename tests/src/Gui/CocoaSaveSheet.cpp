// SPDX-License-Identifier: LGPL-2.1-or-later

#include <QApplication>
#include <QEventLoop>
#include <QFileDialog>
#include <QLineEdit>
#include <QTemporaryDir>
#include <QTest>
#include <QTimer>

#include <App/Application.h>
#include <Base/Tools.h>
#include <Gui/FileDialog.h>
#include <src/App/InitApplication.h>

class testCocoaSaveSheet: public QObject
{
    Q_OBJECT

private Q_SLOTS:
    void initTestCase()
    {
        tests::initApplication();
    }

    void parentedSaveKeepsWindowModality()
    {
        auto parameters = App::GetApplication().GetParameterGroupByPath(
            "User parameter:BaseApp/Preferences/Dialog"
        );
        const bool wasNonNative = parameters->GetBool("DontUseNativeDialog", false);
        parameters->SetBool("DontUseNativeDialog", false);
        QTemporaryDir directory;
        QVERIFY(directory.isValid());
        QWidget parent;
        parent.setWindowTitle(QStringLiteral("Cocoa save-sheet owner"));
        parent.show();
        parent.winId();

        bool observed = false;
        Qt::WindowModality modality = Qt::NonModal;
        QWidget* dialogParent = nullptr;
        QTimer probe;
        // Setup can pump events before the dialog is visible. Keep looking
        // until the modal call returns, rather than missing its only probe.
        probe.setSingleShot(false);
        connect(&probe, &QTimer::timeout, &parent, [&]() {
            auto* dialog = qobject_cast<QFileDialog*>(QApplication::activeModalWidget());
            if (!dialog) {
                for (auto* widget : QApplication::topLevelWidgets()) {
                    dialog = qobject_cast<QFileDialog*>(widget);
                    if (dialog && dialog->isVisible()) {
                        break;
                    }
                }
            }
            if (dialog && dialog->isVisible()) {
                observed = true;
                modality = dialog->windowModality();
                dialogParent = dialog->parentWidget();
                parent.raise();
                parent.activateWindow();
                QMetaObject::invokeMethod(dialog, "reject", Qt::QueuedConnection);
            }
        });
        probe.start(100);
        qsizetype selectedFilter = 0;
        const auto selected = Gui::FileDialog::getSaveFileName(
            &parent,
            QStringLiteral("Save-sheet regression"),
            directory.path(),
            {{QStringLiteral("PDF"), {QStringLiteral("*.pdf")}}},
            &selectedFilter
        );
        probe.stop();
        parameters->SetBool("DontUseNativeDialog", wasNonNative);
        QVERIFY(observed);
        QCOMPARE(dialogParent, &parent);
        QCOMPARE(modality, Qt::WindowModal);
        QVERIFY(selected.isEmpty());
        QCOMPARE(selectedFilter, qsizetype(0));
        QVERIFY(parent.isEnabled());
    }

    void saveDialogSelectionContracts_data()
    {
        QTest::addColumn<bool>("hasParent");
        QTest::addColumn<bool>("nonNativePreference");
        QTest::addColumn<bool>("forceNonNativeOption");
        QTest::addColumn<bool>("acceptSelection");
        QTest::addColumn<int>("expectedModality");
        QTest::addColumn<int>("expectedFilter");
        QTest::addColumn<bool>("probeBeforeDialog");
        QTest::newRow("parented-native-cancel")
            << true << false << false << false << int(Qt::WindowModal) << 0 << false;
        QTest::newRow("parentless-native-cancel")
            << false << false << false << false << int(Qt::ApplicationModal) << 0 << false;
        QTest::newRow("nonnative-preference-cancel")
            << true << true << false << false << int(Qt::ApplicationModal) << 1 << false;
        QTest::newRow("nonnative-preference-accept")
            << true << true << false << true << int(Qt::ApplicationModal) << 1 << false;
        QTest::newRow("forced-widget-option-cancel")
            << true << false << true << false << int(Qt::ApplicationModal) << 0 << false;
        QTest::newRow("forced-widget-option-accept")
            << true << false << true << true << int(Qt::ApplicationModal) << 1 << false;
        QTest::newRow("parented-native-accept")
            << true << false << false << true << int(Qt::WindowModal) << 1 << false;
        QTest::newRow("probe-before-widget-dialog-cancel")
            << true << false << true << false << int(Qt::ApplicationModal) << 0 << true;
    }

    void saveDialogSelectionContracts()
    {
        QFETCH(bool, hasParent);
        QFETCH(bool, nonNativePreference);
        QFETCH(bool, forceNonNativeOption);
        QFETCH(bool, acceptSelection);
        QFETCH(int, expectedModality);
        QFETCH(int, expectedFilter);
        QFETCH(bool, probeBeforeDialog);
        // Qt's static application-modal Cocoa panel has no consistently
        // discoverable visible QWidget, and programmatic accept is not a
        // native Save-button action. Those contracts are covered offscreen;
        // actual native filename/Save delivery is separately GUI-qualified.
        if (QApplication::platformName() == QStringLiteral("cocoa") && !nonNativePreference
            && !forceNonNativeOption && (!hasParent || acceptSelection)) {
            QSKIP("Native static-panel and Save-button paths require the controlled GUI check");
        }
        QTemporaryDir directory;
        QVERIFY(directory.isValid());
        auto parameters = App::GetApplication().GetParameterGroupByPath(
            "User parameter:BaseApp/Preferences/Dialog"
        );
        const bool wasNonNative = parameters->GetBool("DontUseNativeDialog", false);
        Base::ScopeGuard restorePreference([parameters, wasNonNative]() {
            parameters->SetBool("DontUseNativeDialog", wasNonNative);
        });
        parameters->SetBool("DontUseNativeDialog", nonNativePreference);
        QWidget parent;
        parent.show();
        parent.winId();
        bool observed = false;
        Qt::WindowModality modality = Qt::NonModal;
        QWidget* dialogParent = nullptr;
        bool nonNativeOption = false;
        bool watchdogFired = false;
        int emptyProbes = 0;
        QStringList filesBeforeAccept;
        QTimer probe;
        probe.setSingleShot(false);
        QTimer watchdog;
        watchdog.setSingleShot(true);
        connect(&watchdog, &QTimer::timeout, &parent, [&]() {
            watchdogFired = true;
            for (auto* widget : QApplication::topLevelWidgets()) {
                if (auto* dialog = qobject_cast<QFileDialog*>(widget)) {
                    dialog->reject();
                }
            }
        });
        connect(&probe, &QTimer::timeout, &parent, [&]() {
            auto* dialog = qobject_cast<QFileDialog*>(QApplication::activeModalWidget());
            if (!dialog) {
                for (auto* widget : QApplication::topLevelWidgets()) {
                    auto* candidate = qobject_cast<QFileDialog*>(widget);
                    if (candidate && candidate->isVisible()) {
                        dialog = candidate;
                        break;
                    }
                }
            }
            if (dialog && dialog->isVisible()) {
                observed = true;
                modality = dialog->windowModality();
                dialogParent = dialog->parentWidget();
                nonNativeOption = dialog->testOption(QFileDialog::DontUseNativeDialog);
                dialog->selectNameFilter(dialog->nameFilters().at(1));
                if (acceptSelection) {
                    // Use the actual widget name editor. Selecting a path via
                    // selectFile while a file model loads can select a folder
                    // instead, which makes accept navigate rather than close.
                    if (auto* editor = dialog->findChild<QLineEdit*>(QStringLiteral("fileNameEdit"))) {
                        editor->setText(QStringLiteral("selected.txt"));
                    }
                    filesBeforeAccept = dialog->selectedFiles();
                    QMetaObject::invokeMethod(dialog, "accept", Qt::QueuedConnection);
                }
                else {
                    // Do not reject synchronously during a setup event pump:
                    // QDialog::exec may subsequently reset that early result.
                    QMetaObject::invokeMethod(dialog, "reject", Qt::QueuedConnection);
                }
            }
            else {
                ++emptyProbes;
            }
        });
        // A liveness guard, not a one-second file-model performance requirement.
        watchdog.start(5000);
        probe.start(probeBeforeDialog ? 1 : 100);
        if (probeBeforeDialog) {
            // File-dialog setup may process events before a modal widget exists.
            // Exercise that interleaving without relying on machine load.
            QEventLoop earlyEvents;
            QTimer::singleShot(50, &earlyEvents, &QEventLoop::quit);
            earlyEvents.exec();
            QVERIFY(emptyProbes > 0);
        }
        qsizetype selectedFilter = 0;
        const auto selected = Gui::FileDialog::getSaveFileName(
            hasParent ? &parent : nullptr,
            QStringLiteral("Save selection contract"),
            directory.path(),
            {{QStringLiteral("PDF"), {QStringLiteral("*.pdf")}},
             {QStringLiteral("Text"), {QStringLiteral("*.txt")}}},
            &selectedFilter,
            forceNonNativeOption ? QFileDialog::DontUseNativeDialog : QFileDialog::Options()
        );
        watchdog.stop();
        probe.stop();
        QVERIFY(observed);
        QVERIFY2(!watchdogFired, "The dialog did not complete the controlled selection action");
        QCOMPARE(dialogParent, hasParent ? &parent : nullptr);
        QCOMPARE(modality, Qt::WindowModality(expectedModality));
        QCOMPARE(nonNativeOption, nonNativePreference || forceNonNativeOption);
        QCOMPARE(selectedFilter, qsizetype(expectedFilter));
        if (acceptSelection) {
            QVERIFY2(
                filesBeforeAccept.contains(directory.filePath(QStringLiteral("selected.txt"))),
                qPrintable(filesBeforeAccept.join(QStringLiteral(";")))
            );
            QCOMPARE(selected, directory.filePath(QStringLiteral("selected.txt")));
        }
        else {
            QVERIFY(selected.isEmpty());
        }
        QVERIFY(parent.isEnabled());
    }
};

QTEST_MAIN(testCocoaSaveSheet)

#include "CocoaSaveSheet.moc"
