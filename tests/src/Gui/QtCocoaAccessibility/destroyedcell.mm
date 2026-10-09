// SPDX-License-Identifier: LGPL-2.1-or-later
// Stock tree collapse leaves a valid model cell with no visible row.
#include <QApplication>
#include <QAccessible>
#include <QTreeWidget>
#include <QJsonDocument>
#include <QJsonObject>
#include <iostream>
#include <cstdlib>
#include <dlfcn.h>
#import <AppKit/AppKit.h>
#import <objc/runtime.h>

static void stage(const char* name, QJsonObject values = {})
{
    values.insert("stage", name);
    std::cout << QJsonDocument(values).toJson(QJsonDocument::Compact).constData() << std::endl;
}

int main(int argc, char** argv)
{
    QApplication app(argc, argv);
    QAccessible::setActive(true);
    for (int iteration = 0; iteration < 20; ++iteration) {
        @try {
            @autoreleasepool {
                QTreeWidget tree;
                tree.setColumnCount(1);
                auto* branch = new QTreeWidgetItem(&tree, {"Branch"});
                new QTreeWidgetItem(branch, {"Child"});
                branch->setExpanded(true);
                tree.show();
                app.processEvents();
                auto* parent = QAccessible::queryAccessibleInterface(&tree);
                if (!parent || !parent->tableInterface())
                    return 2;
                Class cls = NSClassFromString(@"QMacAccessibilityElement");
                auto method = class_getInstanceMethod(cls, sel_registerName("initWithId:role:"));
                Dl_info image {};
                if (!method || !dladdr(reinterpret_cast<void*>(method_getImplementation(method)), &image))
                    return 2;
                // Cache the Qt cell without constructing its Cocoa wrapper. The ordinary
                // layout notification must construct that wrapper during Qt cache removal.
                auto* cell = parent->tableInterface()->cellAt(1, 0);
                if (!cell || !cell->isValid() || !cell->tableCellInterface())
                    return 2;
                stage("qt_cell_cached", {{"iteration", iteration},
                    {"id", static_cast<qint64>(QAccessible::uniqueId(cell))},
                    {"row", cell->tableCellInterface()->rowIndex()},
                    {"column", cell->tableCellInterface()->columnIndex()},
                    {"plugin", image.dli_fname}});
                branch->setExpanded(false);
                tree.doItemsLayout();
                stage("collapsed_cell", {{"valid", cell->isValid()},
                    {"row", cell->tableCellInterface()->rowIndex()},
                    {"column", cell->tableCellInterface()->columnIndex()}});
                if (!cell->isValid() || cell->tableCellInterface()->rowIndex() != -1)
                    return 3;
                // Never use cell after posted modelChange deletes it.
                app.processEvents();
                if (!parent->isValid() || parent->tableInterface()->rowCount() != 1)
                    return 4;
                branch->setExpanded(true);
                tree.doItemsLayout();
                app.processEvents();
                auto* restored = parent->tableInterface()->cellAt(1, 0);
                if (!restored || !restored->isValid() || !restored->tableCellInterface()
                    || restored->text(QAccessible::Name) != "Child"
                    || restored->tableCellInterface()->rowIndex() != 1)
                    return 5;
                stage("iteration_passed", {{"iteration", iteration}});
            }
        } @catch (NSException* exception) {
            stage("native_exception", {{"name", QString::fromUtf8(exception.name.UTF8String)},
                {"reason", QString::fromUtf8(exception.reason.UTF8String)}});
            std::_Exit(1);
        }
    }
    stage("passed", {{"repeat_count", 20}});
    return 0;
}
