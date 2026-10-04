// SPDX-License-Identifier: LGPL-2.1-or-later

#include <QBuffer>
#include <QPaintEngine>
#include <QPainter>
#include <QPainterPath>
#include <QPdfWriter>
#include <QStyleOptionGraphicsItem>
#include <QTest>
#include <QTransform>

#include <Mod/TechDraw/Gui/QGCustomPath.h>

Q_DECLARE_METATYPE(QPainterPath)

namespace
{

class RecordingPaintEngine: public QPaintEngine
{
public:
    explicit RecordingPaintEngine(Type engineType)
        : QPaintEngine(AllFeatures)
        , engineType(engineType)
    {}

    bool begin(QPaintDevice*) override
    {
        return true;
    }
    bool end() override
    {
        return true;
    }
    Type type() const override
    {
        return engineType;
    }
    void drawPixmap(const QRectF&, const QPixmap&, const QRectF&) override
    {}
    void updateState(const QPaintEngineState& state) override
    {
        pen = state.pen();
        brush = state.brush();
    }
    void drawPath(const QPainterPath& path) override
    {
        ++pathCount;
        paintedPath = path;
    }

    const Type engineType;
    int pathCount {};
    QPainterPath paintedPath;
    QPen pen;
    QBrush brush;
};

class RecordingPdfWriter: public QPdfWriter
{
public:
    RecordingPdfWriter(QIODevice* output, QPaintEngine::Type engineType, PdfVersion version)
        : QPdfWriter(output)
        , engine(engineType)
    {
        setPdfVersion(version);
    }

    QPaintEngine* paintEngine() const override
    {
        return &engine;
    }
    mutable RecordingPaintEngine engine;
};

QPainterPath line(double length)
{
    QPainterPath path(QPointF(100, 100));
    path.lineTo(100 + length, 100);
    return path;
}

}  // namespace

class QGCustomPathTest: public QObject
{
    Q_OBJECT

private Q_SLOTS:
    void paintPreservesVisibleGeometry_data()
    {
        QTest::addColumn<QPainterPath>("path");
        QTest::addColumn<QPen>("pen");
        QTest::addColumn<QBrush>("brush");
        QTest::addColumn<int>("engineType");
        QTest::addColumn<int>("pdfVersion");
        QTest::addColumn<double>("scale");
        QTest::addColumn<int>("drawCount");

        QPen dashed(QColor(0, 0, 0, 128), 2);
        dashed.setCosmetic(false);
        dashed.setCapStyle(Qt::FlatCap);
        dashed.setDashPattern({1, 5});
        dashed.setDashOffset(2);
        const QPainterPath gap = line(0.01);
        const QBrush noBrush(Qt::NoBrush);
        const int pdf = QPaintEngine::Pdf;
        const int user = QPaintEngine::User;
        const int standard = QPagedPaintDevice::PdfVersion_1_4;
        const int archival = QPagedPaintDevice::PdfVersion_A1b;
        QTest::newRow("pdf-gap") << gap << dashed << noBrush << pdf << standard << 1.0 << 0;
        QTest::newRow("pdf-translated-gap")
            << gap.translated(30, -20) << dashed << noBrush << pdf << standard << 1.0 << 0;
        QTest::newRow("pdf-visible-dash")
            << line(10) << dashed << noBrush << pdf << standard << 1.0 << 1;

        QPen solid = dashed;
        solid.setStyle(Qt::SolidLine);
        QTest::newRow("pdf-solid") << gap << solid << noBrush << pdf << standard << 1.0 << 1;
        QPen offsetZero = dashed;
        offsetZero.setDashOffset(0);
        QTest::newRow("pdf-offset-zero")
            << gap << offsetZero << noBrush << pdf << standard << 1.0 << 1;

        QPainterPath filledGap = gap;
        filledGap.lineTo(100.005, 100.01);
        filledGap.closeSubpath();
        QTest::newRow("pdf-filled-gap")
            << filledGap << dashed << QBrush(Qt::red) << pdf << standard << 1.0 << 1;
        QPen cosmetic = dashed;
        cosmetic.setCosmetic(true);
        QTest::newRow("pdf-cosmetic-gap")
            << gap << cosmetic << noBrush << pdf << standard << 1.0 << 1;
        QTest::newRow("pdf-cosmetic-visible-after-scaling")
            << gap << cosmetic << noBrush << pdf << standard << 1000.0 << 1;
        QPen tinyWidth = dashed;
        tinyWidth.setWidthF(0.00001);
        QTest::newRow("pdf-tiny-width") << gap << tinyWidth << noBrush << pdf << standard << 1.0 << 1;
        QTest::newRow("non-pdf-gap") << gap << dashed << noBrush << user << standard << 1.0 << 1;

        QPen opaque = dashed;
        opaque.setColor(Qt::black);
        QTest::newRow("pdf-opaque-gap") << gap << opaque << noBrush << pdf << standard << 1.0 << 1;
        opaque.setDashPattern({0, 5});
        opaque.setDashOffset(0);
        QTest::newRow("pdf-opaque-native-clamped-dash")
            << gap << opaque << noBrush << pdf << standard << 1.0 << 1;
        QTest::newRow("pdf-archival-translucent-gap")
            << gap << dashed << noBrush << pdf << archival << 1.0 << 1;

        QPen roundCap = dashed;
        roundCap.setCapStyle(Qt::RoundCap);
        QTest::newRow("pdf-round-cap-gap")
            << gap << roundCap << noBrush << pdf << standard << 1.0 << 0;
        QPen squareCap = dashed;
        squareCap.setCapStyle(Qt::SquareCap);
        QTest::newRow("pdf-square-cap-gap")
            << gap << squareCap << noBrush << pdf << standard << 1.0 << 0;
    }

    void paintPreservesVisibleGeometry()
    {
        QFETCH(QPainterPath, path);
        QFETCH(QPen, pen);
        QFETCH(QBrush, brush);
        QFETCH(int, engineType);
        QFETCH(int, pdfVersion);
        QFETCH(double, scale);
        QFETCH(int, drawCount);
        QVERIFY(!path.isEmpty());
        TechDrawGui::QGCustomPath item;
        item.setPath(path);
        item.setPen(pen);
        item.setBrush(brush);
        const QRectF bounds = item.boundingRect();
        const QPainterPath shape = item.shape();
        QBuffer output;
        QVERIFY(output.open(QIODevice::WriteOnly));
        RecordingPdfWriter device(
            &output,
            static_cast<QPaintEngine::Type>(engineType),
            static_cast<QPagedPaintDevice::PdfVersion>(pdfVersion)
        );
        QPainter painter(&device);
        QVERIFY(painter.isActive());
        painter.scale(scale, scale);
        QStyleOptionGraphicsItem option;
        item.paint(&painter, &option);
        QCOMPARE(device.engine.pathCount, drawCount);
        if (drawCount != 0) {
            QCOMPARE(device.engine.paintedPath, path);
            QCOMPARE(device.engine.pen, pen);
            QCOMPARE(device.engine.brush, brush);
        }
        QCOMPARE(item.path(), path);
        QCOMPARE(item.pen(), pen);
        QCOMPARE(item.brush(), brush);
        QCOMPARE(item.boundingRect(), bounds);
        QCOMPARE(item.shape(), shape);
    }

    void paintPreservesBackgroundAndPerspective_data()
    {
        QTest::addColumn<bool>("opaqueBackground");
        QTest::newRow("opaque-background") << true;
        QTest::newRow("perspective") << false;
    }

    void paintPreservesBackgroundAndPerspective()
    {
        QFETCH(bool, opaqueBackground);
        const QPainterPath path = line(0.01);
        QPen pen(QColor(0, 0, 0, 128), 2);
        pen.setCosmetic(false);
        pen.setCapStyle(Qt::FlatCap);
        pen.setDashPattern({1, 5});
        pen.setDashOffset(2);
        TechDrawGui::QGCustomPath item;
        item.setPath(path);
        item.setPen(pen);
        item.setBrush(Qt::NoBrush);
        const QRectF bounds = item.boundingRect();
        const QPainterPath shape = item.shape();
        QBuffer output;
        QVERIFY(output.open(QIODevice::WriteOnly));
        RecordingPdfWriter device(&output, QPaintEngine::Pdf, QPagedPaintDevice::PdfVersion_1_4);
        QPainter painter(&device);
        QVERIFY(painter.isActive());
        if (opaqueBackground) {
            painter.setBackground(QBrush(Qt::red));
            painter.setBackgroundMode(Qt::OpaqueMode);
        }
        else {
            painter.setWorldTransform(QTransform(1, 0, 0.001, 0, 1, 0, 0, 0, 1));
            QVERIFY(!painter.worldTransform().isAffine());
        }
        QStyleOptionGraphicsItem option;
        item.paint(&painter, &option);
        QVERIFY(device.engine.pathCount >= 1);
        QCOMPARE(device.engine.paintedPath, path);
        QCOMPARE(device.engine.pen, pen);
        QCOMPARE(device.engine.brush.style(), Qt::NoBrush);
        QCOMPARE(item.path(), path);
        QCOMPARE(item.pen(), pen);
        QCOMPARE(item.brush().style(), Qt::NoBrush);
        QCOMPARE(item.boundingRect(), bounds);
        QCOMPARE(item.shape(), shape);
    }
};

QTEST_MAIN(QGCustomPathTest)
#include "QGCustomPath.moc"
