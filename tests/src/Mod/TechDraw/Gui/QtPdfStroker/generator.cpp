// SPDX-License-Identifier: LGPL-2.1-or-later

#include <QCommandLineParser>
#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QGuiApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLibraryInfo>
#include <QPageLayout>
#include <QPageSize>
#include <QPaintEngine>
#include <QPainter>
#include <QPainterPath>
#include <QPdfWriter>
#include <QPen>
#include <QPluginLoader>
#include <QSysInfo>
#include <QTransform>
#ifdef WITH_QPRINTER
# include <QPrinter>
#endif

#include <functional>
#include <memory>
#include <stdexcept>
#include <utility>

#if defined(Q_OS_MACOS)
# include <mach-o/dyld.h>
#elif defined(Q_OS_LINUX)
# include <link.h>
#elif defined(Q_OS_WIN)
# include <windows.h>
# include <tlhelp32.h>
#endif

namespace
{

struct Fixture
{
    QDir output;
    QStringList devices;
    QJsonArray cases;
};

QStringList loadedModules()
{
    QStringList modules;
#if defined(Q_OS_MACOS)
    for (uint32_t index = 0; index < _dyld_image_count(); ++index) {
        modules.append(QString::fromUtf8(_dyld_get_image_name(index)));
    }
#elif defined(Q_OS_LINUX)
    dl_iterate_phdr(
        [](dl_phdr_info* info, size_t, void* data) {
            if (info->dlpi_name && info->dlpi_name[0]) {
                static_cast<QStringList*>(data)->append(QString::fromLocal8Bit(info->dlpi_name));
            }
            return 0;
        },
        &modules
    );
#elif defined(Q_OS_WIN)
    HANDLE snapshot
        = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, GetCurrentProcessId());
    if (snapshot == INVALID_HANDLE_VALUE) {
        throw std::runtime_error("Cannot enumerate loaded modules");
    }
    MODULEENTRY32W entry {};
    entry.dwSize = sizeof(entry);
    if (Module32FirstW(snapshot, &entry)) {
        do {
            modules.append(QString::fromWCharArray(entry.szExePath));
        } while (Module32NextW(snapshot, &entry));
    }
    CloseHandle(snapshot);
#else
    throw std::runtime_error("Loaded-module proof is unsupported on this platform");
#endif
    modules.removeDuplicates();
    modules.sort();
    return modules;
}

void writeRuntime(const QDir& output)
{
    QJsonArray modules;
    QJsonArray qtModules;
    for (const QString& path : loadedModules()) {
        modules.append(path);
        const QFileInfo info(path);
        const QString name = info.fileName();
        const bool qtLibrary = name.startsWith(QStringLiteral("Qt"))
            || name.startsWith(QStringLiteral("libQt"));
        const bool plugin = (name.startsWith(QStringLiteral("q"))
                             || name.startsWith(QStringLiteral("libq")))
            && (name.endsWith(QStringLiteral(".dll")) || name.endsWith(QStringLiteral(".dylib"))
                || name.endsWith(QStringLiteral(".so")))
            && !QPluginLoader(path).metaData().isEmpty();
        if (qtLibrary || plugin) {
            QFile file(path);
            QCryptographicHash digest(QCryptographicHash::Sha256);
            if (!file.open(QIODevice::ReadOnly) || !digest.addData(&file)) {
                throw std::runtime_error(
                    (QStringLiteral("Cannot hash loaded Qt module: ") + path).toStdString()
                );
            }
            qtModules.append(
                QJsonObject {
                    {QStringLiteral("path"), info.canonicalFilePath()},
                    {QStringLiteral("sha256"), QString::fromLatin1(digest.result().toHex())},
                    {QStringLiteral("kind"),
                     qtLibrary ? QStringLiteral("library") : QStringLiteral("plugin")},
                }
            );
        }
    }
    const QJsonObject runtime {
        {QStringLiteral("schema_version"), 1},
        {QStringLiteral("qt_version"), QString::fromLatin1(qVersion())},
        {QStringLiteral("platform"), QSysInfo::kernelType()},
        {QStringLiteral("architecture"), QSysInfo::currentCpuArchitecture()},
        {QStringLiteral("build_abi"), QSysInfo::buildAbi()},
        {QStringLiteral("configured_prefix"), QLibraryInfo::path(QLibraryInfo::PrefixPath)},
        {QStringLiteral("platform_plugin"), QGuiApplication::platformName()},
        {QStringLiteral("loaded_modules"), modules},
        {QStringLiteral("qt_modules"), qtModules},
    };
    QFile file(output.filePath(QStringLiteral("runtime.json")));
    if (!file.open(QIODevice::WriteOnly)) {
        throw std::runtime_error("Cannot write runtime proof");
    }
    file.write(QJsonDocument(runtime).toJson(QJsonDocument::Indented));
}

QPainterPath line(qreal length, QPointF start = QPointF(100, 100))
{
    QPainterPath path(start);
    path.lineTo(start + QPointF(length, 0));
    return path;
}

QPen strokePen()
{
    QPen pen(QColor(0, 0, 0, 128), 2);
    pen.setCosmetic(false);
    pen.setCapStyle(Qt::FlatCap);
    return pen;
}

void draw(QPainter& painter, const QPainterPath& path, const QPen& pen, const QBrush& brush = Qt::NoBrush)
{
    painter.setPen(pen);
    painter.setBrush(brush);
    painter.drawPath(path);
}

void addCase(
    Fixture& fixture,
    const QString& name,
    bool expectInk,
    int baselineInvalidCloses,
    const std::function<void(QPainter&)>& paint,
    const QString& expectedColor = {},
    QPagedPaintDevice::PdfVersion version = QPagedPaintDevice::PdfVersion_1_4
)
{
    for (const QString& deviceName : fixture.devices) {
        const QString caseName = deviceName + QStringLiteral(":") + name;
        const QString filename = (deviceName == QStringLiteral("qpdfwriter")
                                      ? name
                                      : deviceName + QStringLiteral("-") + name)
            + QStringLiteral(".pdf");
        std::unique_ptr<QPagedPaintDevice> device;
        const QPageSize page(QSizeF(200, 200), QPageSize::Point);
        if (deviceName == QStringLiteral("qpdfwriter")) {
            auto writer = std::make_unique<QPdfWriter>(fixture.output.filePath(filename));
            writer->setResolution(72);
            writer->setPageSize(page);
            writer->setPageMargins(QMarginsF(), QPageLayout::Point);
            writer->setPdfVersion(version);
            writer->setCreator(QStringLiteral("Qt PDF stroker qualification"));
            writer->setTitle(name);
            device = std::move(writer);
        }
#ifdef WITH_QPRINTER
        else {
            auto printer = std::make_unique<QPrinter>(QPrinter::HighResolution);
            printer->setOutputFormat(QPrinter::PdfFormat);
            printer->setOutputFileName(fixture.output.filePath(filename));
            printer->setResolution(72);
            printer->setFullPage(true);
            printer->setPageSize(page);
            printer->setPageMargins(QMarginsF(), QPageLayout::Point);
            printer->setPdfVersion(version);
            printer->setColorMode(QPrinter::Color);
            printer->setCreator(QStringLiteral("Qt PDF stroker qualification"));
            printer->setDocName(name);
            device = std::move(printer);
        }
#endif
        QPainter painter;
        if (!painter.begin(device.get())) {
            throw std::runtime_error("Cannot begin PDF painter");
        }
        if (painter.paintEngine()->type() != QPaintEngine::Pdf) {
            throw std::runtime_error("Paint device did not select Qt's PDF engine");
        }
        paint(painter);
        if (!painter.end()) {
            throw std::runtime_error("Cannot finish PDF painter");
        }
        fixture.cases.append(
            QJsonObject {
                {QStringLiteral("name"), caseName},
                {QStringLiteral("device"), deviceName},
                {QStringLiteral("scenario"), name},
                {QStringLiteral("pdf"), filename},
                {QStringLiteral("expect_ink"), expectInk},
                {QStringLiteral("expected_color"), expectedColor},
                {QStringLiteral("baseline_invalid_closes"), baselineInvalidCloses},
                {QStringLiteral("pdf_version"), static_cast<int>(version)},
            }
        );
    }
}

}  // namespace

int main(int argc, char** argv)
{
    if (qEnvironmentVariableIsEmpty("QT_QPA_PLATFORM")) {
        qputenv("QT_QPA_PLATFORM", "offscreen");
    }
    QGuiApplication app(argc, argv);
    QCommandLineParser parser;
    parser.setApplicationDescription(QStringLiteral("Generate Qt-only PDF stroker cases"));
    parser.addHelpOption();
    QCommandLineOption outputOption(
        {QStringLiteral("o"), QStringLiteral("output")},
        QStringLiteral("Output directory"),
        QStringLiteral("directory")
    );
    parser.addOption(outputOption);
    QCommandLineOption deviceOption(
        QStringLiteral("device"),
        QStringLiteral("Paint device: qpdfwriter, qprinter, or both"),
        QStringLiteral("device"),
        QStringLiteral("qpdfwriter")
    );
    parser.addOption(deviceOption);
    parser.process(app);
    if (!parser.isSet(outputOption)) {
        parser.showHelp(2);
    }
    QDir output(parser.value(outputOption));
    if (!output.mkpath(QStringLiteral("."))) {
        throw std::runtime_error("Cannot create output directory");
    }
    const QString selectedDevice = parser.value(deviceOption);
    if (selectedDevice != QStringLiteral("qpdfwriter")
        && selectedDevice != QStringLiteral("qprinter") && selectedDevice != QStringLiteral("both")) {
        parser.showHelp(2);
    }
#ifndef WITH_QPRINTER
    if (selectedDevice != QStringLiteral("qpdfwriter")) {
        qCritical("QPrinter requires a fixture configured with -DWITH_QPRINTER=ON");
        return 2;
    }
#endif
    Fixture fixture {
        output,
        selectedDevice == QStringLiteral("both")
            ? QStringList {QStringLiteral("qpdfwriter"), QStringLiteral("qprinter")}
            : QStringList {selectedDevice},
        {}
    };
    const QPen solid = strokePen();
    QPen dashed = solid;
    dashed.setDashPattern({1, 5});
    dashed.setDashOffset(2);
    const QPainterPath gap = line(0.01);

    addCase(fixture, "empty", false, 1, [&](QPainter& p) { draw(p, QPainterPath(), solid); });
    addCase(fixture, "move-only", false, 1, [&](QPainter& p) {
        draw(p, QPainterPath(QPointF(100, 100)), solid);
    });
    addCase(fixture, "coincident-line", false, 1, [&](QPainter& p) { draw(p, line(0), solid); });
    addCase(fixture, "dash-gap", false, 1, [&](QPainter& p) { draw(p, gap, dashed); });
    addCase(fixture, "visible-dash", true, 0, [&](QPainter& p) { draw(p, line(10), dashed); });
    addCase(fixture, "solid-line", true, 0, [&](QPainter& p) { draw(p, line(10), solid); });
    addCase(fixture, "null-rectangle", false, 1, [&](QPainter& p) {
        p.setPen(solid);
        p.setBrush(Qt::NoBrush);
        p.drawRect(QRectF(100, 100, 0, 0));
    });
    addCase(fixture, "horizontal-rectangle", true, 0, [&](QPainter& p) {
        p.setPen(solid);
        p.setBrush(Qt::NoBrush);
        p.drawRect(QRectF(90, 100, 20, 0));
    });
    addCase(fixture, "vertical-rectangle", true, 0, [&](QPainter& p) {
        p.setPen(solid);
        p.setBrush(Qt::NoBrush);
        p.drawRect(QRectF(100, 90, 0, 20));
    });
    addCase(fixture, "fully-clipped-stroke", false, 0, [&](QPainter& p) {
        p.setClipRect(QRectF(0, 0, 20, 20));
        draw(p, line(10), solid);
    });
    addCase(fixture, "partially-clipped-stroke", true, 0, [&](QPainter& p) {
        p.setClipRect(QRectF(100, 90, 5, 20));
        draw(p, line(10), solid);
    });
    QPen zeroOffset = dashed;
    zeroOffset.setDashOffset(0);
    addCase(fixture, "offset-zero", true, 0, [&](QPainter& p) { draw(p, line(1), zeroOffset); });

    for (const auto& cap :
         {std::make_pair(QStringLiteral("round"), Qt::RoundCap),
          std::make_pair(QStringLiteral("square"), Qt::SquareCap)}) {
        QPen pen = dashed;
        pen.setCapStyle(cap.second);
        addCase(fixture, cap.first + "-cap-gap", false, 1, [&](QPainter& p) { draw(p, gap, pen); });
        pen.setDashOffset(0);
        addCase(fixture, cap.first + "-cap-visible", true, 0, [&](QPainter& p) {
            draw(p, line(1), pen);
        });
    }

    QPainterPath rectangle;
    rectangle.addRect(90, 90, 20, 20);
    QPen fillGap = dashed;
    fillGap.setDashPattern({1, 1000});
    addCase(
        fixture,
        "visible-fill-empty-stroke",
        true,
        1,
        [&](QPainter& p) { draw(p, rectangle, fillGap, QBrush(Qt::blue)); },
        "blue"
    );
    addCase(
        fixture,
        "visible-fill-solid-stroke",
        true,
        0,
        [&](QPainter& p) { draw(p, rectangle, solid, QBrush(Qt::blue)); },
        "blue"
    );
    addCase(
        fixture,
        "visible-fill-no-pen",
        true,
        0,
        [&](QPainter& p) { draw(p, rectangle, QPen(Qt::NoPen), QBrush(Qt::blue)); },
        "blue"
    );
    addCase(
        fixture,
        "opaque-background",
        true,
        1,
        [&](QPainter& p) {
            p.setBackground(QBrush(Qt::red));
            p.setBackgroundMode(Qt::OpaqueMode);
            draw(p, gap, dashed);
        },
        "red"
    );

    QPen cosmetic = dashed;
    cosmetic.setCosmetic(true);
    addCase(fixture, "cosmetic-gap", false, 1, [&](QPainter& p) { draw(p, gap, cosmetic); });
    addCase(fixture, "cosmetic-visible-scaled", true, 0, [&](QPainter& p) {
        p.translate(100, 100);
        p.scale(1000, 1000);
        draw(p, line(0.01, QPointF()), cosmetic);
    });
    addCase(fixture, "cosmetic-gap-scaled-down", false, 1, [&](QPainter& p) {
        p.translate(100, 100);
        p.scale(0.001, 0.001);
        draw(p, line(10, QPointF()), cosmetic);
    });
    QPen zeroWidth = dashed;
    zeroWidth.setWidthF(0);
    addCase(fixture, "zero-width-visible", true, 0, [&](QPainter& p) {
        draw(p, line(20), zeroWidth);
    });
    for (const auto& width :
         {std::make_pair(QStringLiteral("tiny-normalized-width"), 0.00001),
          std::make_pair(QStringLiteral("minimum-real-width"), 0.0001)}) {
        QPen pen = dashed;
        pen.setWidthF(width.second);
        addCase(fixture, width.first, true, 0, [&](QPainter& p) {
            p.translate(50, 100);
            p.scale(10000, 10000);
            draw(p, line(0.01, QPointF()), pen);
        });
    }

    QPainterPath coordinated = line(10);
    coordinated.moveTo(100, 110);
    coordinated.cubicTo(103, 115, 107, 105, 110, 110);
    coordinated.moveTo(100, 120);
    coordinated.lineTo(100.01, 120);
    addCase(fixture, "coordinated-curve-and-gap", true, 0, [&](QPainter& p) {
        draw(p, coordinated, dashed);
    });
    addCase(fixture, "gap-visible-gap-calls", true, 2, [&](QPainter& p) {
        draw(p, gap, dashed);
        draw(p, line(10), dashed);
        draw(p, gap.translated(0, 10), dashed);
    });
    addCase(fixture, "empty-visible-empty-calls", true, 2, [&](QPainter& p) {
        draw(p, QPainterPath(), solid);
        draw(p, line(10), solid);
        draw(p, QPainterPath(), solid);
    });
    addCase(fixture, "perspective-visible", true, 0, [&](QPainter& p) {
        p.setWorldTransform(QTransform(1, 0, 0.001, 0, 1, 0, 0, 0, 1));
        draw(p, line(10), dashed);
    });
    addCase(fixture, "perspective-gap", false, 0, [&](QPainter& p) {
        p.setWorldTransform(QTransform(1, 0, 0.001, 0, 1, 0, 0, 0, 1));
        draw(p, gap, dashed);
    });

    QPen nativeClamp = solid;
    nativeClamp.setColor(Qt::black);
    nativeClamp.setDashPattern({0, 5});
    nativeClamp.setDashOffset(0);
    addCase(fixture, "opaque-native-clamp", true, 0, [&](QPainter& p) {
        p.scale(100000, 100000);
        draw(p, line(0.01, QPointF()), nativeClamp);
    });
    nativeClamp.setColor(QColor(0, 0, 0, 128));
    addCase(
        fixture,
        "archival-native-clamp",
        true,
        0,
        [&](QPainter& p) {
            p.scale(100000, 100000);
            draw(p, line(0.01, QPointF()), nativeClamp);
        },
        {},
        QPagedPaintDevice::PdfVersion_A1b
    );

    QFile manifest(output.filePath(QStringLiteral("manifest.json")));
    if (!manifest.open(QIODevice::WriteOnly)) {
        throw std::runtime_error("Cannot write manifest");
    }
    const QJsonObject result {
        {QStringLiteral("schema_version"), 2},
        {QStringLiteral("qt_version"), QString::fromLatin1(qVersion())},
        {QStringLiteral("raster_dpi"), 100},
        {QStringLiteral("cases"), fixture.cases},
    };
    manifest.write(QJsonDocument(result).toJson(QJsonDocument::Indented));
    writeRuntime(output);
    return 0;
}
