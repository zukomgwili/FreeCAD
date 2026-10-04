// SPDX-License-Identifier: LGPL-2.1-or-later

#include <QPaintEngine>
#include <QPainter>
#include <QStyleOptionGraphicsItem>
#include <QTest>

#include <Mod/TechDraw/Gui/QGCustomRect.h>

namespace
{

class RecordingPaintEngine: public QPaintEngine
{
public:
    RecordingPaintEngine()
        : QPaintEngine(AllFeatures)
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
        return User;
    }
    void drawPixmap(const QRectF&, const QPixmap&, const QRectF&) override
    {}
    void updateState(const QPaintEngineState& state) override
    {
        pen = state.pen();
        brush = state.brush();
    }
    void drawRects(const QRectF* rects, int count) override
    {
        rectCount += count;
        if (count > 0) {
            paintedRect = rects[0];
        }
    }
    void drawPath(const QPainterPath&) override
    {
        ++pathCount;
    }

    int rectCount {};
    int pathCount {};
    QRectF paintedRect;
    QPen pen;
    QBrush brush;
};

class RecordingPaintDevice: public QPaintDevice
{
public:
    QPaintEngine* paintEngine() const override
    {
        return &engine;
    }
    mutable RecordingPaintEngine engine;

protected:
    int metric(PaintDeviceMetric metric) const override
    {
        switch (metric) {
            case PdmWidth:
            case PdmHeight:
                return 100;
            case PdmDpiX:
            case PdmDpiY:
            case PdmPhysicalDpiX:
            case PdmPhysicalDpiY:
                return 96;
            case PdmDevicePixelRatioScaled:
                return QPaintDevice::devicePixelRatioFScale();
            default:
                return 1;
        }
    }
};

void paintItem(QGraphicsItem& item, RecordingPaintDevice& device)
{
    QPainter painter(&device);
    QVERIFY(painter.isActive());
    QStyleOptionGraphicsItem option;
    option.state |= QStyle::State_Selected;
    item.paint(&painter, &option);
}

}  // namespace

class QGCustomRectTest: public QObject
{
    Q_OBJECT

private Q_SLOTS:
    void nullRectangleIsNotPainted_data()
    {
        QTest::addColumn<QRectF>("rect");
        QTest::newRow("origin") << QRectF();
        QTest::newRow("translated") << QRectF(10, 20, 0, 0);
    }

    void nullRectangleIsNotPainted()
    {
        QFETCH(QRectF, rect);
        QVERIFY(rect.isNull());
        TechDrawGui::QGCustomRect item;
        item.setRect(rect);
        item.setPen(QPen(QColor(0, 0, 0, 216), 2));
        RecordingPaintDevice device;
        paintItem(item, device);
        QCOMPARE(device.engine.rectCount, 0);
        QCOMPARE(device.engine.pathCount, 0);
    }

    void nonnullRectangleIsPainted_data()
    {
        QTest::addColumn<QRectF>("rect");
        QTest::newRow("ordinary") << QRectF(10, 10, 20, 20);
        QTest::newRow("horizontal") << QRectF(10, 10, 20, 0);
        QTest::newRow("vertical") << QRectF(10, 10, 0, 20);
        QTest::newRow("negative") << QRectF(30, 30, -20, -20);
    }

    void nonnullRectangleIsPainted()
    {
        QFETCH(QRectF, rect);
        QVERIFY(!rect.isNull());
        const QPen pen(QColor(0, 0, 0, 216), 2);
        const QBrush brush(Qt::red);
        TechDrawGui::QGCustomRect item;
        item.setRect(rect);
        item.setPen(pen);
        item.setBrush(brush);
        RecordingPaintDevice device;
        paintItem(item, device);
        QCOMPARE(device.engine.rectCount, 1);
        QCOMPARE(device.engine.pathCount, 0);
        QCOMPARE(device.engine.paintedRect, rect);
        QCOMPARE(device.engine.pen, pen);
        QCOMPARE(device.engine.brush, brush);
    }
};

QTEST_MAIN(QGCustomRectTest)
#include "QGCustomRect.moc"
