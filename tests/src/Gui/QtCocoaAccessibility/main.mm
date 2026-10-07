// SPDX-License-Identifier: LGPL-2.1-or-later
// Stock-widget regression for the native Qt Cocoa accessibility selection bridge.
#include <QApplication>
#include <QAccessible>
#include <QAbstractItemView>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QItemSelectionModel>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLibraryInfo>
#include <QListWidget>
#include <QStringList>
#include <QTableWidget>
#include <QThread>
#include <QTreeWidget>
#include <iostream>
#include <memory>
#include <cstdlib>
#include <dlfcn.h>
#import <AppKit/AppKit.h>
#import <objc/message.h>
#import <objc/runtime.h>

static void stage(const char* name, QJsonObject details = {})
{
    details.insert("stage", QString::fromLatin1(name));
    std::cout << QJsonDocument(details).toJson(QJsonDocument::Compact).constData()
              << std::endl;  // endl flushes the marker before every risky native call.
}

static int fail(const char* message, QJsonObject details = {})
{
    details.insert("message", QString::fromLatin1(message));
    stage("failed", details);
    return 1;
}

static QString objDescription(id value)
{
    if (!value) {
        return {};
    }
    const char* utf8 = [[value description] UTF8String];
    return utf8 ? QString::fromUtf8(utf8) : QString();
}

static id getIdProperty(id object, const char* name)
{
    SEL selector = sel_registerName(name);
    if (![object respondsToSelector:selector]) {
        return nil;
    }
    using Getter = id (*)(id, SEL);
    return reinterpret_cast<Getter>(objc_msgSend)(object, selector);
}

static int tableLifecycle(QApplication& app, int repeats)
{
    QTableWidget table(3, 2);
    table.setSelectionMode(QAbstractItemView::SingleSelection);
    table.setSelectionBehavior(QAbstractItemView::SelectRows);
    table.setWindowTitle("Qt Cocoa selected children stock table lifecycle");
    table.resize(360, 220);
    table.show();
    table.activateWindow();
    QElapsedTimer exposedWait;
    exposedWait.start();
    while (exposedWait.elapsed() < 250) {
        app.processEvents(QEventLoop::AllEvents, 10);
        QThread::msleep(5);
    }
    if (!table.isVisible()) {
        return fail("stock lifecycle table is not visible");
    }

    Class cocoaClass = NSClassFromString(@"QMacAccessibilityElement");
    SEL factorySelector = sel_registerName("elementWithId:");
    SEL selectedSelector = sel_registerName("accessibilitySelectedChildren");
    if (!cocoaClass || ![cocoaClass respondsToSelector:factorySelector]) {
        return fail("registered Cocoa class lacks actual accessible element factory");
    }
    Method method = class_getInstanceMethod(cocoaClass, selectedSelector);
    Dl_info implementationImage {};
    if (!method
        || !dladdr(reinterpret_cast<void*>(method_getImplementation(method)), &implementationImage)
        || !implementationImage.dli_fname) {
        return fail("could not bind lifecycle selector to loaded image");
    }
    const QString implementationPath = QString::fromLocal8Bit(implementationImage.dli_fname);
    if (!implementationPath.endsWith("/libqcocoa.dylib")) {
        return fail("lifecycle selector is not from the actual Cocoa plugin");
    }
    stage(
        "native_selector_identified",
        {{"class", "QMacAccessibilityElement"},
         {"selector", "accessibilitySelectedChildren"},
         {"implementation_image", implementationPath}}
    );

    QAccessibleInterface* initialInterface = QAccessible::queryAccessibleInterface(&table);
    if (!initialInterface || !initialInterface->isValid()) {
        return fail("lifecycle table has no valid Qt accessibility interface");
    }
    const QAccessible::Id parentId = QAccessible::uniqueId(initialInterface);
    auto stableParent = [&]() {
        QAccessibleInterface* current = QAccessible::accessibleInterface(parentId);
        return current && current->isValid() && current->object() == &table
            && QAccessible::uniqueId(QAccessible::queryAccessibleInterface(&table)) == parentId;
    };
    auto populate = [&]() {
        for (int row = 0; row < table.rowCount(); ++row) {
            for (int column = 0; column < table.columnCount(); ++column) {
                if (!table.item(row, column)) {
                    table.setItem(
                        row,
                        column,
                        new QTableWidgetItem(QStringLiteral("Row %1 column %2").arg(row).arg(column))
                    );
                }
            }
        }
    };
    using Factory = id (*)(id, SEL, QAccessible::Id);
    using Getter = id (*)(id, SEL);
    auto check = [&](int iteration, const char* phase, int selectedRow) -> int {
        app.processEvents();
        const int expectedCount = table.columnCount();
        const QJsonObject context {
            {"iteration", iteration},
            {"phase", QString::fromLatin1(phase)},
            {"row_count", table.rowCount()},
            {"column_count", expectedCount},
            {"selected_row", selectedRow},
            {"accessible_id", static_cast<qint64>(parentId)}
        };
        if (!stableParent()) {
            return fail("table lifecycle removed or replaced the live parent interface", context);
        }
        const auto indexes = table.selectionModel()->selectedIndexes();
        const auto selectedRows = table.selectionModel()->selectedRows();
        if (indexes.size() != expectedCount || selectedRows.size() != 1
            || selectedRows.first().row() != selectedRow) {
            return fail("table lifecycle has an unexpected actual Qt row selection", context);
        }
        for (const QModelIndex& index : indexes) {
            if (index.row() != selectedRow) {
                return fail("table lifecycle selected an unexpected Qt row", context);
            }
        }

        @autoreleasepool {
            // Resolve a fresh native representation after every model/selection change.
            stage("before_native_factory", context);
            id nativeElement = reinterpret_cast<Factory>(objc_msgSend)(
                reinterpret_cast<id>(cocoaClass),
                factorySelector,
                parentId
            );
            if (!nativeElement || ![nativeElement respondsToSelector:selectedSelector]) {
                return fail("lifecycle factory did not return a selected-children element", context);
            }
            stage("before_native_table_rows", context);
            id rowsValue = getIdProperty(nativeElement, "accessibilityRows");
            if (![rowsValue isKindOfClass:[NSArray class]] ||
                [(NSArray*)rowsValue count] != static_cast<NSUInteger>(table.rowCount())) {
                return fail("native lifecycle row count disagrees with the stock table", context);
            }
            for (id rowElement in (NSArray*)rowsValue) {
                id cellsValue = getIdProperty(rowElement, "accessibilityChildren");
                if (![cellsValue isKindOfClass:[NSArray class]] ||
                    [(NSArray*)cellsValue count] != static_cast<NSUInteger>(expectedCount)) {
                    return fail("native lifecycle row children disagree with the stock table", context);
                }
                for (id cell in (NSArray*)cellsValue) {
                    if (![getIdProperty(cell, "accessibilityRole")
                            isEqualToString:NSAccessibilityCellRole]) {
                        return fail("materialized native lifecycle child is not an AXCell", context);
                    }
                }
            }
            stage("native_table_rows_materialized", context);
            if (!stableParent()) {
                return fail("materializing native rows removed the live table interface", context);
            }
            QAccessibleInterface* current = QAccessible::accessibleInterface(parentId);
            QAccessibleSelectionInterface* selection = current->selectionInterface();
            if (!selection) {
                return fail("lifecycle table lost its actual Qt selection interface", context);
            }
            const auto qtSelected = selection->selectedItems();
            if (selection->selectedItemCount() != expectedCount
                || qtSelected.size() != expectedCount) {
                return fail("actual Qt accessibility selection disagrees with the selected row", context);
            }
            QStringList qtSelectedNames;
            for (QAccessibleInterface* child : qtSelected) {
                if (!child || !child->isValid() || child->role() != QAccessible::Cell) {
                    return fail("actual lifecycle Qt selected cell is invalid", context);
                }
                const QString name = child->text(QAccessible::Name);
                if (name.isEmpty()) {
                    return fail("actual lifecycle Qt selected cell has an empty fixture label", context);
                }
                qtSelectedNames.append(name);
            }
            stage("before_native_selected_children", context);
            id returned = reinterpret_cast<Getter>(objc_msgSend)(nativeElement, selectedSelector);
            if (!stableParent()) {
                return fail("lifecycle native query removed the live table interface", context);
            }
            if (![returned isKindOfClass:[NSArray class]] ||
                [(NSArray*)returned count] != static_cast<NSUInteger>(expectedCount)) {
                return fail(
                    "native lifecycle selection count disagrees with actual Qt selection",
                    context
                );
            }
            QStringList nativeSelectedNames;
            for (id child in (NSArray*)returned) {
                if (![getIdProperty(child, "accessibilityRole")
                        isEqualToString:NSAccessibilityCellRole]) {
                    return fail("native lifecycle selected child is not an AXCell", context);
                }
                const QString name = objDescription(getIdProperty(child, "accessibilityTitle"));
                if (name.isEmpty()) {
                    return fail("native lifecycle selected cell has an empty fixture label", context);
                }
                nativeSelectedNames.append(name);
            }
            qtSelectedNames.sort();
            nativeSelectedNames.sort();
            if (nativeSelectedNames != qtSelectedNames) {
                return fail("native lifecycle selected cells disagree with actual Qt selection", context);
            }
            QJsonObject observed = context;
            observed.insert("native_selected_count", static_cast<qint64>([(NSArray*)returned count]));
            observed.insert("qt_selected_names", QJsonArray::fromStringList(qtSelectedNames));
            observed.insert("native_selected_names", QJsonArray::fromStringList(nativeSelectedNames));
            stage("native_selected_children_returned", observed);
        }
        if (!stableParent()) {
            return fail("draining native lifecycle elements removed the live parent interface", context);
        }
        return 0;
    };

    @try {
        for (int iteration = 0; iteration < repeats; ++iteration) {
            table.setColumnCount(2);
            table.setRowCount(3);
            populate();
            table.selectRow(0);
            if (int result = check(iteration, "select_row_0", 0)) {
                return result;
            }
            table.selectRow(1);
            if (int result = check(iteration, "select_row_1", 1)) {
                return result;
            }
            table.setColumnCount(3);
            populate();
            // Include the added cell through an ordinary row-selection operation.
            table.selectRow(1);
            if (int result = check(iteration, "grow_columns", 1)) {
                return result;
            }
            table.setColumnCount(2);
            if (int result = check(iteration, "shrink_columns", 1)) {
                return result;
            }
            table.setRowCount(2);
            if (int result = check(iteration, "shrink_rows", 1)) {
                return result;
            }
        }
    }
    @catch (NSException* exception) {
        return fail(
            "native table lifecycle raised Objective-C exception",
            {{"exception_name", objDescription(exception.name)},
             {"exception_reason", objDescription(exception.reason)}}
        );
    }
    stage(
        "passed",
        {{"mode", "table-lifecycle"},
         {"repeat_count", repeats},
         {"selection_queries_each_iteration", 5},
         {"implementation_image", implementationPath}}
    );
    return 0;
}

int main(int argc, char** argv)
{
    if (argc < 2 || argc > 4) {
        std::cerr << "usage: selector-repro tree|list|table [repeat-count] [selected-count]; "
                     "selector-repro table-lifecycle [repeat-count]"
                  << std::endl;
        return 2;
    }
    const QString mode = QString::fromLocal8Bit(argv[1]);
    if (mode != "tree" && mode != "list" && mode != "table" && mode != "table-lifecycle") {
        return fail("mode must be tree, list, table, or table-lifecycle");
    }
    if (mode == "table-lifecycle" && argc == 4) {
        return fail("table-lifecycle does not accept selected-count");
    }
    int repeats = 1;
    if (argc >= 3) {
        bool ok = false;
        repeats = QString::fromLocal8Bit(argv[2]).toInt(&ok);
        if (!ok || repeats < 1 || repeats > 100000) {
            return fail("repeat-count must be an integer from 1 to 100000");
        }
    }
    const int expectedCount = argc == 4 ? QString::fromLocal8Bit(argv[3]).toInt() : 2;
    if (expectedCount < 0 || expectedCount > 2) {
        return fail("selected-count must be 0, 1, or 2");
    }
    stage("before_qapplication", {{"mode", mode}, {"repeat_count", repeats}});
    QApplication app(argc, argv);
    QAccessible::setActive(true);
    stage(
        "qapplication_ready",
        {{"qt_version", QString::fromLatin1(qVersion())},
         {"platform", QApplication::platformName()},
         {"qt_prefix", QLibraryInfo::path(QLibraryInfo::PrefixPath)},
         {"qt_plugins", QLibraryInfo::path(QLibraryInfo::PluginsPath)}}
    );
    if (QApplication::platformName() != "cocoa") {
        return fail("real cocoa platform required");
    }
    if (mode == "table-lifecycle") {
        return tableLifecycle(app, repeats);
    }

    std::unique_ptr<QAbstractItemView> view;
    if (mode == "tree") {
        auto* tree = new QTreeWidget;
        tree->setColumnCount(1);
        tree->setHeaderLabel("Stock tree item");
        tree->setSelectionMode(QAbstractItemView::ExtendedSelection);
        auto* a = new QTreeWidgetItem(tree, QStringList {"Selected alpha"});
        auto* b = new QTreeWidgetItem(tree, QStringList {"Selected beta"});
        a->setSelected(expectedCount >= 1);
        b->setSelected(expectedCount >= 2);
        view.reset(tree);
    }
    else if (mode == "list") {
        auto* list = new QListWidget;
        list->setSelectionMode(QAbstractItemView::ExtendedSelection);
        auto* a = new QListWidgetItem("Selected alpha", list);
        auto* b = new QListWidgetItem("Selected beta", list);
        a->setSelected(expectedCount >= 1);
        b->setSelected(expectedCount >= 2);
        view.reset(list);
    }
    else {
        auto* table = new QTableWidget(2, 1);
        table->setSelectionMode(QAbstractItemView::ExtendedSelection);
        table->setSelectionBehavior(QAbstractItemView::SelectItems);
        auto* a = new QTableWidgetItem("Selected alpha");
        auto* b = new QTableWidgetItem("Selected beta");
        table->setItem(0, 0, a);
        table->setItem(1, 0, b);
        a->setSelected(expectedCount >= 1);
        b->setSelected(expectedCount >= 2);
        view.reset(table);
    }
    view->setWindowTitle("Qt Cocoa selected children stock " + mode);
    view->resize(360, 220);
    view->show();
    view->activateWindow();
    QElapsedTimer exposedWait;
    exposedWait.start();
    while (exposedWait.elapsed() < 250) {
        app.processEvents(QEventLoop::AllEvents, 10);
        QThread::msleep(5);
    }
    stage(
        "stock_widget_shown",
        {{"visible", view->isVisible()},
         {"qt_selected_indexes", view->selectionModel()->selectedIndexes().size()}}
    );
    if (!view->isVisible()) {
        return fail("stock widget is not visible");
    }
    if (view->selectionModel()->selectedIndexes().size() != expectedCount) {
        return fail("stock widget must contain the requested number of genuinely selected indexes");
    }

    QAccessibleInterface* iface = QAccessible::queryAccessibleInterface(view.get());
    if (!iface || !iface->isValid()) {
        return fail("stock widget has no valid Qt accessibility interface");
    }
    QAccessibleSelectionInterface* selection = iface->selectionInterface();
    if (!selection) {
        return fail("stock widget has no actual Qt accessibility selection interface");
    }
    Class cocoaClass = NSClassFromString(@"QMacAccessibilityElement");
    if (!cocoaClass) {
        return fail("loaded platform plugin did not register QMacAccessibilityElement");
    }
    SEL factorySelector = sel_registerName("elementWithId:");
    SEL selectedSelector = sel_registerName("accessibilitySelectedChildren");
    if (![cocoaClass respondsToSelector:factorySelector]) {
        return fail("registered Cocoa class lacks actual accessible element factory");
    }
    Method method = class_getInstanceMethod(cocoaClass, selectedSelector);
    if (!method) {
        return fail("registered Cocoa class lacks actual selected children selector");
    }
    Dl_info implementationImage {};
    IMP implementation = method_getImplementation(method);
    if (!dladdr(reinterpret_cast<void*>(implementation), &implementationImage)
        || !implementationImage.dli_fname) {
        return fail("could not bind real native selector implementation to loaded image");
    }
    const QString implementationPath = QString::fromLocal8Bit(implementationImage.dli_fname);
    stage(
        "native_selector_identified",
        {{"class", "QMacAccessibilityElement"},
         {"selector", "accessibilitySelectedChildren"},
         {"implementation_image", implementationPath}}
    );
    if (!implementationPath.endsWith("/libqcocoa.dylib")) {
        return fail("selected children implementation is not from the actual Cocoa plugin");
    }
    using Factory = id (*)(id, SEL, QAccessible::Id);
    const QAccessible::Id accessibleId = QAccessible::uniqueId(iface);
    stage("before_native_factory", {{"accessible_id", static_cast<qint64>(accessibleId)}});
    id nativeElement = reinterpret_cast<Factory>(objc_msgSend)(
        reinterpret_cast<id>(cocoaClass),
        factorySelector,
        accessibleId
    );
    if (!nativeElement || ![nativeElement respondsToSelector:selectedSelector]) {
        return fail("actual Cocoa factory did not return an element supporting selected children");
    }

    @try {
        for (int iteration = 0; iteration < repeats; ++iteration) {
            @autoreleasepool {
                const auto qtSelected = selection->selectedItems();
                const int qtCount = selection->selectedItemCount();
                QJsonArray selectedTexts;
                QStringList qtSelectedNames;
                if (qtCount != expectedCount || qtSelected.size() != expectedCount) {
                    return fail(
                        "actual Qt accessibility selection precondition changed",
                        {{"iteration", iteration},
                         {"selected_count", qtCount},
                         {"selected_list_size", qtSelected.size()}}
                    );
                }
                for (QAccessibleInterface* child : qtSelected) {
                    if (!child || !child->isValid()) {
                        return fail("actual selected child is invalid", {{"iteration", iteration}});
                    }
                    const QString name = child->text(QAccessible::Name);
                    if (name.isEmpty()) {
                        return fail(
                            "actual Qt selected child has an empty fixture label",
                            {{"iteration", iteration}}
                        );
                    }
                    selectedTexts.append(name);
                    qtSelectedNames.append(name);
                }
                stage(
                    "before_native_selected_children",
                    {{"iteration", iteration},
                     {"qt_selected_count", qtCount},
                     {"qt_selected_names", selectedTexts}}
                );
                using Getter = id (*)(id, SEL);
                id returned = reinterpret_cast<Getter>(objc_msgSend)(nativeElement, selectedSelector);
                if (!QAccessible::accessibleInterface(accessibleId)) {
                    return fail("native query removed the live widget accessibility interface");
                }
                if (!returned || ![returned isKindOfClass:[NSArray class]]) {
                    return fail(
                        "actual Cocoa selector did not return an array",
                        {{"iteration", iteration}}
                    );
                }
                NSArray* nativeChildren = (NSArray*)returned;
                stage(
                    "native_selected_children_returned",
                    {{"iteration", iteration},
                     {"native_selected_count", static_cast<qint64>([nativeChildren count])}}
                );
                QJsonArray children;
                QStringList nativeSelectedNames;
                for (id child in nativeChildren) {
                    const QString name = objDescription(getIdProperty(child, "accessibilityTitle"));
                    if (name.isEmpty()) {
                        return fail(
                            "native selected child has an empty fixture label",
                            {{"iteration", iteration}}
                        );
                    }
                    nativeSelectedNames.append(name);
                    children.append(
                        QJsonObject {
                            {"class", QString::fromLatin1(object_getClassName(child))},
                            {"role", objDescription(getIdProperty(child, "accessibilityRole"))},
                            {"title", name},
                            {"label", objDescription(getIdProperty(child, "accessibilityLabel"))},
                            {"value", objDescription(getIdProperty(child, "accessibilityValue"))}
                        }
                    );
                }
                stage(
                    "native_selected_children_observed",
                    {{"iteration", iteration}, {"children", children}}
                );
                if ([nativeChildren count] != static_cast<NSUInteger>(expectedCount)) {
                    return fail(
                        "actual native selected children count disagrees with actual Qt selection",
                        {{"iteration", iteration},
                         {"qt_selected_count", qtCount},
                         {"native_selected_count", static_cast<qint64>([nativeChildren count])}}
                    );
                }
                qtSelectedNames.sort();
                nativeSelectedNames.sort();
                if (nativeSelectedNames != qtSelectedNames) {
                    return fail(
                        "native selected children disagree with actual Qt selection",
                        {{"iteration", iteration},
                         {"qt_selected_names", QJsonArray::fromStringList(qtSelectedNames)},
                         {"native_selected_names", QJsonArray::fromStringList(nativeSelectedNames)}}
                    );
                }
            }
        }
    }
    @catch (NSException* exception) {
        return fail(
            "actual native selected children raised Objective-C exception",
            {{"exception_name", objDescription(exception.name)},
             {"exception_reason", objDescription(exception.reason)}}
        );
    }
    stage(
        "passed",
        {{"mode", mode},
         {"repeat_count", repeats},
         {"native_selected_count_each_iteration", expectedCount},
         {"implementation_image", implementationPath}}
    );
    return 0;
}
