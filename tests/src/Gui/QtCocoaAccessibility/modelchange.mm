// SPDX-License-Identifier: LGPL-2.1-or-later
// Regression for Cocoa table representations deleting Qt-owned cell interfaces.
#include <QAbstractItemView>
#include <QAccessible>
#include <QApplication>
#include <QDir>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QFile>
#include <QFileDialog>
#include <QItemSelectionModel>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLibraryInfo>
#include <QLineEdit>
#include <QTest>
#include <QPersistentModelIndex>
#include <QStringList>
#include <QTableWidget>
#include <QTemporaryDir>
#include <QThread>
#include <QTreeView>
#include <QTreeWidget>
#include <QVector>
#include <functional>
#include <iostream>
#include <dlfcn.h>
#import <AppKit/AppKit.h>
#import <objc/message.h>
#import <objc/runtime.h>

static void stage(const char* name, QJsonObject details = {})
{
    details.insert("stage", QString::fromLatin1(name));
    std::cout << QJsonDocument(details).toJson(QJsonDocument::Compact).constData() << std::endl;
}

static int fail(const char* message, QJsonObject details = {})
{
    details.insert("message", QString::fromLatin1(message));
    stage("failed", details);
    return 1;
}

static QString describe(id value)
{
    const char* utf8 = value ? [[value description] UTF8String] : nullptr;
    return utf8 ? QString::fromUtf8(utf8) : QString();
}

static id property(id object, const char* name)
{
    SEL selector = sel_registerName(name);
    if (!object || ![object respondsToSelector:selector]) {
        return nil;
    }
    using Getter = id (*)(id, SEL);
    return reinterpret_cast<Getter>(objc_msgSend)(object, selector);
}

static bool waitFor(QApplication& app, const std::function<bool()>& condition, int timeout = 3000)
{
    QElapsedTimer timer;
    timer.start();
    do {
        app.processEvents(QEventLoop::AllEvents, 10);
        if (condition()) {
            return true;
        }
        QThread::msleep(5);
    } while (timer.elapsed() < timeout);
    return false;
}

struct CellIdentity
{
    QAccessible::Id id;
    QString name;
    QPersistentModelIndex index;
};

class NativeView
{
public:
    explicit NativeView(QAbstractItemView& view)
        : view(view)
    {}

    int initialize()
    {
        QAccessibleInterface* iface = QAccessible::queryAccessibleInterface(&view);
        if (!iface || !iface->isValid() || !iface->tableInterface()
            || !iface->selectionInterface()) {
            return fail("stock view lacks real Qt table and selection interfaces");
        }
        parentId = QAccessible::uniqueId(iface);
        cocoaClass = NSClassFromString(@"QMacAccessibilityElement");
        SEL selected = sel_registerName("accessibilitySelectedChildren");
        Method method = cocoaClass ? class_getInstanceMethod(cocoaClass, selected) : nullptr;
        Dl_info image {};
        if (!cocoaClass || ![cocoaClass respondsToSelector:sel_registerName("elementWithId:")]
            || !method
            || !dladdr(reinterpret_cast<void*>(method_getImplementation(method)), &image)
            || !image.dli_fname) {
            return fail("cannot identify actual registered Cocoa element factory and selector");
        }
        implementationPath = QString::fromLocal8Bit(image.dli_fname);
        if (!implementationPath.endsWith("/libqcocoa.dylib")) {
            return fail("native selector does not come from actual Cocoa plugin");
        }
        stage(
            "native_selector_identified",
            {{"selector", "accessibilitySelectedChildren"},
             {"implementation_image", implementationPath},
             {"parent_id", static_cast<qint64>(parentId)}}
        );
        return 0;
    }

    int verifyTracked(int iteration, const char* phase)
    {
        auto *parent = QAccessible::accessibleInterface(parentId);
        if (!parent || !parent->isValid() || !parent->tableInterface())
            return fail("tracked cells lost their live Qt parent");
        QJsonArray observed;
        for (CellIdentity& saved : trackedCells) {
            if (!saved.index.isValid())
                continue; // Removed model cells are correctly owned and deleted by Qt.
            auto *atIndex = parent->tableInterface()->cellAt(saved.index.row(), saved.index.column());
            const bool current = atIndex && atIndex->isValid() && atIndex->tableCellInterface()
                && atIndex->text(QAccessible::Name) == saved.name;
            if (!current)
                return fail("surviving model cell lacks a valid current Qt interface", {{"iteration", iteration},
                    {"phase", phase}, {"cells", observed}});
            const QAccessible::Id currentId = QAccessible::uniqueId(atIndex);
            const bool same = currentId == saved.id;
            const bool oldRegistered = !same && QAccessible::accessibleInterface(saved.id);
            observed.append(QJsonObject{{"previous_id", static_cast<qint64>(saved.id)},
                {"current_id", static_cast<qint64>(currentId)}, {"name", saved.name},
                {"row", saved.index.row()}, {"column", saved.index.column()},
                {"identity_preserved", same}, {"previous_identity_still_registered", oldRegistered}});
            saved.id = currentId;
        }
        stage("surviving_cell_ids_verified", {{"iteration", iteration}, {"phase", phase}, {"cells", observed}});
        return 0;
    }

    // Called within the iteration's autoreleasepool. No native object escapes it.
    int query(int iteration, const char* phase, const QString& expectedSelectedName)
    {
        const QJsonObject context {
            {"iteration", iteration},
            {"phase", QString::fromLatin1(phase)},
            {"parent_id", static_cast<qint64>(parentId)}
        };
        QAccessibleInterface* iface = QAccessible::accessibleInterface(parentId);
        if (!iface || !iface->isValid() || iface->object() != &view
            || QAccessible::uniqueId(QAccessible::queryAccessibleInterface(&view)) != parentId) {
            return fail("live Qt view interface was removed or replaced", context);
        }
        QAccessibleTableInterface* table = iface->tableInterface();
        QAccessibleSelectionInterface* selection = iface->selectionInterface();
        if (!table || !selection) {
            return fail("live view lost table or selection interface", context);
        }
        if (int result = verifyTracked(iteration, phase))
            return result;
        const auto selected = selection->selectedItems();
        if (selected.isEmpty() || selection->selectedItemCount() != selected.size()
            || view.selectionModel()->selectedIndexes().size() != selected.size()) {
            return fail("actual selected Qt indexes and accessibility cells disagree", context);
        }
        survivingCells.clear();
        QStringList qtNames;
        for (QAccessibleInterface* cell : selected) {
            if (!cell || !cell->isValid() || !cell->tableCellInterface()) {
                return fail("selected Qt accessibility cell is missing", context);
            }
            const QString name = cell->text(QAccessible::Name);
            qtNames.append(name);
            survivingCells.append({QAccessible::uniqueId(cell), name, {}});
        }
        if (!qtNames.contains(expectedSelectedName)) {
            return fail("actual Qt selection lost surviving fixture item", context);
        }
        using Factory = id (*)(id, SEL, QAccessible::Id);
        stage("before_native_factory", context);
        id native = reinterpret_cast<Factory>(objc_msgSend)(
            reinterpret_cast<id>(cocoaClass),
            sel_registerName("elementWithId:"),
            parentId
        );
        stage("before_native_rows", context);
        id rowsValue = property(native, "accessibilityRows");
        if (![rowsValue isKindOfClass:[NSArray class]]
            || [(NSArray*)rowsValue count] != static_cast<NSUInteger>(table->rowCount())) {
            return fail("actual Cocoa rows disagree with current Qt table", context);
        }
        int rowIndex = 0;
        for (id row : (NSArray*)rowsValue) {
            id children = property(row, "accessibilityChildren");
            if (![children isKindOfClass:[NSArray class]]
                || [(NSArray*)children count] != static_cast<NSUInteger>(table->columnCount())) {
                return fail("actual Cocoa row children disagree with current Qt table", context);
            }
            int columnIndex = 0;
            for (id child : (NSArray*)children) {
                const int column = columnIndex++;
                QAccessibleInterface* qtCell = table->cellAt(rowIndex, column);
                if (!qtCell || !qtCell->isValid()) {
                    return fail("current Qt table cell is missing after native conversion", context);
                }
                id role = property(child, "accessibilityRole");
                if (![role isKindOfClass:[NSString class]] || [(NSString*)role length] == 0)
                    return fail("native materialized table child lacks an accessibility role", context);
                const QPersistentModelIndex modelIndex(view.model()->index(rowIndex, column, view.rootIndex()));
                if (!modelIndex.isValid())
                    return fail("materialized cell has no actual model index", context);
                bool known = false;
                for (const CellIdentity& saved : trackedCells)
                    known = known || saved.index == modelIndex;
                if (!known && view.selectionModel()->isSelected(modelIndex))
                    trackedCells.append({QAccessible::uniqueId(qtCell), qtCell->text(QAccessible::Name), modelIndex});
                if (describe(property(child, "accessibilityTitle")) != qtCell->text(QAccessible::Name)) {
                    return fail("actual Cocoa row cell text differs from current Qt cell", context);
                }
            }
            ++rowIndex;
        }
        stage("before_native_selected_children", context);
        id nativeSelected = property(native, "accessibilitySelectedChildren");
        if (![nativeSelected isKindOfClass:[NSArray class]]
            || [(NSArray*)nativeSelected count] != static_cast<NSUInteger>(selected.size())) {
            return fail("actual Cocoa selection count disagrees with selected Qt cells", context);
        }
        QStringList nativeNames;
        QStringList nativeRoles;
        for (id cell : (NSArray*)nativeSelected) {
            id role = property(cell, "accessibilityRole");
            if (![role isKindOfClass:[NSString class]] || [(NSString*)role length] == 0)
                return fail("native selected table child lacks an accessibility role", context);
            nativeRoles.append(describe(role));
            nativeNames.append(describe(property(cell, "accessibilityTitle")));
        }
        nativeRoles.sort();
        nativeNames.sort();
        qtNames.sort();
        if (qtNames != nativeNames) {
            return fail("actual Cocoa selected cell identities disagree with Qt selection", context);
        }
        QJsonObject observed = context;
        observed.insert("qt_selected_names", QJsonArray::fromStringList(qtNames));
        observed.insert("native_selected_names", QJsonArray::fromStringList(nativeNames));
        observed.insert("native_selected_roles", QJsonArray::fromStringList(nativeRoles));
        observed.insert("row_count", table->rowCount());
        observed.insert("column_count", table->columnCount());
        stage("native_cells_match", observed);
        return 0;
    }

    int afterPool(int iteration)
    {
        if (int result = verifyTracked(iteration, "after_native_pool_drain"))
            return result;
        QJsonArray identities;
        bool valid = true;
        for (const CellIdentity& saved : survivingCells) {
            QAccessibleInterface* current = QAccessible::accessibleInterface(saved.id);
            const bool stable = current && current->isValid() && current->tableCellInterface()
                && QAccessible::uniqueId(current) == saved.id
                && current->text(QAccessible::Name) == saved.name;
            valid = valid && stable;
            identities.append(
                QJsonObject {
                    {"id", static_cast<qint64>(saved.id)},
                    {"name", saved.name},
                    {"same_live_interface", stable}
                }
            );
        }
        const QJsonObject context {{"iteration", iteration}, {"surviving_cells", identities}};
        stage("iteration_pool_drained", context);
        if (!valid) {
            return fail("native autoreleasepool drain deleted a surviving Qt cell interface", context);
        }
        return 0;
    }

    QString implementationPath;

private:
    QAbstractItemView& view;
    QAccessible::Id parentId = 0;
    Class cocoaClass = Nil;
    QVector<CellIdentity> survivingCells;
    QVector<CellIdentity> trackedCells;
};

static int tableChanges(QApplication& app, int repeats)
{
    QTableWidget table(3, 2);
    table.setSelectionMode(QAbstractItemView::SingleSelection);
    table.setSelectionBehavior(QAbstractItemView::SelectRows);
    table.setWindowTitle("Qt Cocoa table model change regression");
    table.resize(420, 240);
    auto populate = [&]() {
        for (int row = 0; row < table.rowCount(); ++row) {
            for (int column = 0; column < table.columnCount(); ++column) {
                if (!table.item(row, column)) {
                    table.setItem(row, column, new QTableWidgetItem(QString("Row %1 column %2").arg(row).arg(column)));
                }
            }
        }
    };
    populate();
    table.show();
    if (!waitFor(app, [&]() { return table.isVisible(); })) {
        return fail("stock table is not visible");
    }
    NativeView observer(table);
    if (int result = observer.initialize()) {
        return result;
    }
    for (int iteration = 0; iteration < repeats; ++iteration) {
        @autoreleasepool {
            stage("before_model_insertions", {{"iteration", iteration}});
            table.setColumnCount(2);
            table.setRowCount(3);
            populate();
            table.selectRow(1);
            if (int result = observer.query(iteration, "initial_rows", "Row 1 column 0")) {
                return result;
            }
            table.setColumnCount(3);
            populate();
            table.selectRow(1);
            if (int result = observer.query(iteration, "columns_inserted", "Row 1 column 0")) {
                return result;
            }
            stage("before_model_removals", {{"iteration", iteration}});
            table.setColumnCount(2);
            if (int result = observer.query(iteration, "columns_removed", "Row 1 column 0")) {
                return result;
            }
            table.setRowCount(2);
            if (int result = observer.query(iteration, "rows_removed", "Row 1 column 0")) {
                return result;
            }
        }
        if (int result = observer.afterPool(iteration)) {
            return result;
        }
    }
    stage("passed", {{"mode", "table"}, {"repeat_count", repeats}, {"implementation_image", observer.implementationPath}});
    return 0;
}

static int treeChanges(QApplication& app, int repeats)
{
    QTreeWidget tree;
    tree.setColumnCount(2);
    tree.setSelectionMode(QAbstractItemView::SingleSelection);
    tree.setSelectionBehavior(QAbstractItemView::SelectRows);
    tree.setWindowTitle("Qt Cocoa tree model change regression");
    tree.resize(420, 240);
    auto* survivor = new QTreeWidgetItem(&tree, {"Surviving alpha", "Surviving beta"});
    new QTreeWidgetItem(&tree, {"Other alpha", "Other beta"});
    tree.show();
    if (!waitFor(app, [&]() { return tree.isVisible(); })) {
        return fail("stock tree is not visible");
    }
    NativeView observer(tree);
    if (int result = observer.initialize()) {
        return result;
    }
    for (int iteration = 0; iteration < repeats; ++iteration) {
        @autoreleasepool {
            tree.setCurrentItem(survivor);
            survivor->setSelected(true);
            if (int result = observer.query(iteration, "initial_rows", "Surviving alpha")) {
                return result;
            }
            stage("before_model_insertions", {{"iteration", iteration}});
            auto* inserted = new QTreeWidgetItem({"Inserted alpha", "Inserted beta"});
            tree.insertTopLevelItem(0, inserted);
            app.processEvents();
            if (int result = observer.query(iteration, "rows_inserted", "Surviving alpha")) {
                return result;
            }
            stage("before_model_removals", {{"iteration", iteration}});
            delete tree.takeTopLevelItem(tree.indexOfTopLevelItem(inserted));
            app.processEvents();
            if (int result = observer.query(iteration, "rows_removed", "Surviving alpha")) {
                return result;
            }
        }
        if (int result = observer.afterPool(iteration)) {
            return result;
        }
    }
    stage("passed", {{"mode", "tree"}, {"repeat_count", repeats}, {"implementation_image", observer.implementationPath}});
    return 0;
}

static QModelIndex findFile(QTreeView& view, const QString& name)
{
    for (int row = 0; row < view.model()->rowCount(view.rootIndex()); ++row) {
        const QModelIndex index = view.model()->index(row, 0, view.rootIndex());
        if (index.data().toString() == name) {
            return index;
        }
    }
    return {};
}

static bool writeFixture(const QString& path)
{
    QFile file(path);
    return file.open(QIODevice::WriteOnly) && file.write("Qt Cocoa regression fixture\n") > 0;
}

static int dialogChanges(QApplication& app, int repeats)
{
    QTemporaryDir fixture;
    if (!fixture.isValid() || !writeFixture(fixture.filePath("surviving.txt"))
        || !writeFixture(fixture.filePath("other.txt"))
        || !QDir(fixture.path()).mkdir("fixture-directory")) {
        return fail("cannot create own temporary file-dialog fixture");
    }
    QFileDialog dialog(nullptr, "Qt Cocoa stock nonnative Save model change regression");
    dialog.setOption(QFileDialog::DontUseNativeDialog, true);
    dialog.setAcceptMode(QFileDialog::AcceptSave);
    dialog.setFileMode(QFileDialog::AnyFile);
    dialog.setViewMode(QFileDialog::Detail);
    dialog.setDirectory(fixture.path());
    dialog.selectFile("surviving.txt");
    dialog.show();
    QTreeView* tree = dialog.findChild<QTreeView*>("treeView");
    if (!tree || !waitFor(app, [&]() { return tree->isVisible() && findFile(*tree, "surviving.txt").isValid(); })) {
        return fail("ordinary nonnative QFileDialog did not populate its filesystem view");
    }
    const QPersistentModelIndex survivor(findFile(*tree, "surviving.txt"));
    auto selectSurvivor = [&]() {
        tree->selectionModel()->setCurrentIndex(
            survivor,
            QItemSelectionModel::ClearAndSelect | QItemSelectionModel::Rows
        );
    };
    selectSurvivor();
    NativeView observer(*tree);
    if (int result = observer.initialize()) {
        return result;
    }
    for (int iteration = 0; iteration < repeats; ++iteration) {
        @autoreleasepool {
            selectSurvivor();
            if (int result = observer.query(iteration, "initial_directory", "surviving.txt")) {
                return result;
            }
            stage("before_filesystem_insertions", {{"iteration", iteration}});
            if (!writeFixture(fixture.filePath("inserted.txt"))
                || !QDir(fixture.path()).mkdir("inserted-directory")
                || !waitFor(app, [&]() { return findFile(*tree, "inserted.txt").isValid() && findFile(*tree, "inserted-directory").isValid(); })) {
                return fail("own filesystem inserts did not reach ordinary QFileDialog model");
            }
            selectSurvivor();
            if (int result = observer.query(iteration, "filesystem_inserted", "surviving.txt")) {
                return result;
            }
            stage("before_filesystem_removals", {{"iteration", iteration}});
            if (!QFile::remove(fixture.filePath("inserted.txt"))
                || !QDir(fixture.path()).rmdir("inserted-directory")
                || !waitFor(app, [&]() { return !findFile(*tree, "inserted.txt").isValid() && !findFile(*tree, "inserted-directory").isValid(); })) {
                return fail("own filesystem removals did not reach ordinary QFileDialog model");
            }
            selectSurvivor();
            if (int result = observer.query(iteration, "filesystem_removed", "surviving.txt")) {
                return result;
            }
        }
        if (!survivor.isValid() || survivor.data().toString() != "surviving.txt") {
            return fail("filesystem fixture lost its persistent surviving Qt model index");
        }
        if (int result = observer.afterPool(iteration)) {
            return result;
        }
    }
    QLineEdit* filename = dialog.findChild<QLineEdit*>("fileNameEdit");
    const QString output = fixture.filePath("ordinary-filename-entry.pdf");
    if (!filename)
        return fail("ordinary Save dialog lacks filename edit");
    filename->setFocus();
    filename->selectAll();
    QTest::keyClicks(filename, output);
    if (filename->text() != output)
        return fail("ordinary filename key entry differs from fixture path",
            {{"expected", output}, {"actual", filename->text()}});
    QString acceptedFile;
    QObject::connect(&dialog, &QFileDialog::fileSelected, &dialog,
        [&](const QString& selected) { acceptedFile = selected; });
    stage("before_ordinary_filename_return", {{"filename", output}});
    QTest::keyClick(filename, Qt::Key_Return);
    if (!waitFor(app, [&]() { return !dialog.isVisible(); })
        || dialog.result() != QDialog::Accepted || acceptedFile != output)
        return fail("ordinary filename Return did not accept the exact stock Save path",
            {{"visible", dialog.isVisible()}, {"result", dialog.result()},
             {"selected_files", QJsonArray::fromStringList(dialog.selectedFiles())},
             {"filename", filename->text()},
             {"modal", app.activeModalWidget() ? app.activeModalWidget()->metaObject()->className() : "none"}});
    if (QFile::exists(output))
        return fail("filename-only fixture unexpectedly wrote output bytes");
    stage("ordinary_filename_accepted", {{"accepted_file", acceptedFile},
        {"output_written", false}});
    stage("passed", {{"mode", "file-dialog"}, {"repeat_count", repeats}, {"implementation_image", observer.implementationPath}, {"fixture_scope", "own QTemporaryDir only"}});
    dialog.reject();
    return 0;
}

int main(int argc, char** argv)
{
    if (argc < 2 || argc > 3) {
        std::cerr << "usage: modelchange-repro table|tree|file-dialog [repeat-count]" << std::endl;
        return 2;
    }
    const QString mode = QString::fromLocal8Bit(argv[1]);
    if (mode != "table" && mode != "tree" && mode != "file-dialog") {
        return fail("mode must be table, tree, or file-dialog");
    }
    bool parsed = true;
    const int repeats = argc == 3 ? QString::fromLocal8Bit(argv[2]).toInt(&parsed) : 3;
    if (!parsed || repeats < 1 || repeats > 100) {
        return fail("repeat-count must be an integer from 1 to 100");
    }
    stage("before_qapplication", {{"mode", mode}, {"repeat_count", repeats}});
    QApplication app(argc, argv);
    QAccessible::setActive(true);
    stage("qapplication_ready", {{"qt_version", qVersion()}, {"platform", QApplication::platformName()}, {"qt_prefix", QLibraryInfo::path(QLibraryInfo::PrefixPath)}});
    if (QApplication::platformName() != "cocoa") {
        return fail("real Cocoa platform is required");
    }
    @try {
        if (mode == "table") {
            return tableChanges(app, repeats);
        }
        if (mode == "tree") {
            return treeChanges(app, repeats);
        }
        return dialogChanges(app, repeats);
    }
    @catch (NSException* exception) {
        return fail("actual Cocoa selector raised Objective-C exception", {{"exception_name", describe(exception.name)}, {"exception_reason", describe(exception.reason)}});
    }
}
