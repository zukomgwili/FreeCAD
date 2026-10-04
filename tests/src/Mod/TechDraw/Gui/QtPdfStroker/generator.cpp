// SPDX-License-Identifier: LGPL-2.1-or-later

#include <QCommandLineParser>
#include <QDir>
#include <QFile>
#include <QGuiApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPageLayout>
#include <QPageSize>
#include <QPainter>
#include <QPainterPath>
#include <QPdfWriter>
#include <QPen>
#include <QTransform>

#include <functional>
#include <stdexcept>
#include <utility>

namespace
{

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
    const QDir& output,
    QJsonArray& cases,
    const QString& name,
    bool expectInk,
    int baselineInvalidCloses,
    const std::function<void(QPainter&)>& paint,
    const QString& expectedColor = {},
    QPagedPaintDevice::PdfVersion version = QPagedPaintDevice::PdfVersion_1_4
)
{
    const QString filename = name + QStringLiteral(".pdf");
    QPdfWriter writer(output.filePath(filename));
    writer.setResolution(72);
    writer.setPageSize(QPageSize(QSizeF(200, 200), QPageSize::Point));
    writer.setPageMargins(QMarginsF(), QPageLayout::Point);
    writer.setPdfVersion(version);
    writer.setCreator(QStringLiteral("Qt PDF stroker qualification"));
    writer.setTitle(name);
    QPainter painter;
    if (!painter.begin(&writer)) {
        throw std::runtime_error("Cannot begin PDF painter");
    }
    paint(painter);
    if (!painter.end()) {
        throw std::runtime_error("Cannot finish PDF painter");
    }
    cases.append(
        QJsonObject {
            {QStringLiteral("name"), name},
            {QStringLiteral("pdf"), filename},
            {QStringLiteral("expect_ink"), expectInk},
            {QStringLiteral("expected_color"), expectedColor},
            {QStringLiteral("baseline_invalid_closes"), baselineInvalidCloses},
            {QStringLiteral("pdf_version"), static_cast<int>(version)},
        }
    );
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
    parser.process(app);
    if (!parser.isSet(outputOption)) {
        parser.showHelp(2);
    }
    QDir output(parser.value(outputOption));
    if (!output.mkpath(QStringLiteral("."))) {
        throw std::runtime_error("Cannot create output directory");
    }
    QJsonArray cases;
    const QPen solid = strokePen();
    QPen dashed = solid;
    dashed.setDashPattern({1, 5});
    dashed.setDashOffset(2);
    const QPainterPath gap = line(0.01);

    addCase(output, cases, "empty", false, 1, [&](QPainter& p) { draw(p, QPainterPath(), solid); });
    addCase(output, cases, "move-only", false, 1, [&](QPainter& p) {
        draw(p, QPainterPath(QPointF(100, 100)), solid);
    });
    addCase(output, cases, "coincident-line", false, 1, [&](QPainter& p) { draw(p, line(0), solid); });
    addCase(output, cases, "dash-gap", false, 1, [&](QPainter& p) { draw(p, gap, dashed); });
    addCase(output, cases, "visible-dash", true, 0, [&](QPainter& p) { draw(p, line(10), dashed); });
    addCase(output, cases, "solid-line", true, 0, [&](QPainter& p) { draw(p, line(10), solid); });
    addCase(output, cases, "null-rectangle", false, 1, [&](QPainter& p) {
        p.setPen(solid);
        p.setBrush(Qt::NoBrush);
        p.drawRect(QRectF(100, 100, 0, 0));
    });
    addCase(output, cases, "horizontal-rectangle", true, 0, [&](QPainter& p) {
        p.setPen(solid);
        p.setBrush(Qt::NoBrush);
        p.drawRect(QRectF(90, 100, 20, 0));
    });
    addCase(output, cases, "vertical-rectangle", true, 0, [&](QPainter& p) {
        p.setPen(solid);
        p.setBrush(Qt::NoBrush);
        p.drawRect(QRectF(100, 90, 0, 20));
    });
    addCase(output, cases, "fully-clipped-stroke", false, 0, [&](QPainter& p) {
        p.setClipRect(QRectF(0, 0, 20, 20));
        draw(p, line(10), solid);
    });
    addCase(output, cases, "partially-clipped-stroke", true, 0, [&](QPainter& p) {
        p.setClipRect(QRectF(100, 90, 5, 20));
        draw(p, line(10), solid);
    });
    QPen zeroOffset = dashed;
    zeroOffset.setDashOffset(0);
    addCase(output, cases, "offset-zero", true, 0, [&](QPainter& p) { draw(p, line(1), zeroOffset); });

    for (const auto& cap :
         {std::make_pair(QStringLiteral("round"), Qt::RoundCap),
          std::make_pair(QStringLiteral("square"), Qt::SquareCap)}) {
        QPen pen = dashed;
        pen.setCapStyle(cap.second);
        addCase(output, cases, cap.first + "-cap-gap", false, 1, [&](QPainter& p) {
            draw(p, gap, pen);
        });
        pen.setDashOffset(0);
        addCase(output, cases, cap.first + "-cap-visible", true, 0, [&](QPainter& p) {
            draw(p, line(1), pen);
        });
    }

    QPainterPath rectangle;
    rectangle.addRect(90, 90, 20, 20);
    QPen fillGap = dashed;
    fillGap.setDashPattern({1, 1000});
    addCase(
        output,
        cases,
        "visible-fill-empty-stroke",
        true,
        1,
        [&](QPainter& p) { draw(p, rectangle, fillGap, QBrush(Qt::blue)); },
        "blue"
    );
    addCase(
        output,
        cases,
        "visible-fill-solid-stroke",
        true,
        0,
        [&](QPainter& p) { draw(p, rectangle, solid, QBrush(Qt::blue)); },
        "blue"
    );
    addCase(
        output,
        cases,
        "visible-fill-no-pen",
        true,
        0,
        [&](QPainter& p) { draw(p, rectangle, QPen(Qt::NoPen), QBrush(Qt::blue)); },
        "blue"
    );
    addCase(
        output,
        cases,
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
    addCase(output, cases, "cosmetic-gap", false, 1, [&](QPainter& p) { draw(p, gap, cosmetic); });
    addCase(output, cases, "cosmetic-visible-scaled", true, 0, [&](QPainter& p) {
        p.translate(100, 100);
        p.scale(1000, 1000);
        draw(p, line(0.01, QPointF()), cosmetic);
    });
    addCase(output, cases, "cosmetic-gap-scaled-down", false, 1, [&](QPainter& p) {
        p.translate(100, 100);
        p.scale(0.001, 0.001);
        draw(p, line(10, QPointF()), cosmetic);
    });
    QPen zeroWidth = dashed;
    zeroWidth.setWidthF(0);
    addCase(output, cases, "zero-width-visible", true, 0, [&](QPainter& p) {
        draw(p, line(20), zeroWidth);
    });
    for (const auto& width :
         {std::make_pair(QStringLiteral("tiny-normalized-width"), 0.00001),
          std::make_pair(QStringLiteral("minimum-real-width"), 0.0001)}) {
        QPen pen = dashed;
        pen.setWidthF(width.second);
        addCase(output, cases, width.first, true, 0, [&](QPainter& p) {
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
    addCase(output, cases, "coordinated-curve-and-gap", true, 0, [&](QPainter& p) {
        draw(p, coordinated, dashed);
    });
    addCase(output, cases, "gap-visible-gap-calls", true, 2, [&](QPainter& p) {
        draw(p, gap, dashed);
        draw(p, line(10), dashed);
        draw(p, gap.translated(0, 10), dashed);
    });
    addCase(output, cases, "empty-visible-empty-calls", true, 2, [&](QPainter& p) {
        draw(p, QPainterPath(), solid);
        draw(p, line(10), solid);
        draw(p, QPainterPath(), solid);
    });
    addCase(output, cases, "perspective-visible", true, 0, [&](QPainter& p) {
        p.setWorldTransform(QTransform(1, 0, 0.001, 0, 1, 0, 0, 0, 1));
        draw(p, line(10), dashed);
    });
    addCase(output, cases, "perspective-gap", false, 0, [&](QPainter& p) {
        p.setWorldTransform(QTransform(1, 0, 0.001, 0, 1, 0, 0, 0, 1));
        draw(p, gap, dashed);
    });

    QPen nativeClamp = solid;
    nativeClamp.setColor(Qt::black);
    nativeClamp.setDashPattern({0, 5});
    nativeClamp.setDashOffset(0);
    addCase(output, cases, "opaque-native-clamp", true, 0, [&](QPainter& p) {
        p.scale(100000, 100000);
        draw(p, line(0.01, QPointF()), nativeClamp);
    });
    nativeClamp.setColor(QColor(0, 0, 0, 128));
    addCase(
        output,
        cases,
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
        {QStringLiteral("schema_version"), 1},
        {QStringLiteral("qt_version"), QString::fromLatin1(qVersion())},
        {QStringLiteral("raster_dpi"), 100},
        {QStringLiteral("cases"), cases},
    };
    manifest.write(QJsonDocument(result).toJson(QJsonDocument::Indented));
    return 0;
}
