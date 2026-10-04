// SPDX-License-Identifier: LGPL-2.1-or-later

#include "QGCustomPath.h"

#include <QPaintEngine>
#include <QPainter>
#include <QPainterPathStroker>
#include <QPdfWriter>
#include <QPrinter>

namespace TechDrawGui
{

namespace
{

bool supportsTransparentPdf(QPainter* painter)
{
    const auto* engine = painter->paintEngine();
    if (!engine || engine->type() != QPaintEngine::Pdf) {
        return false;
    }
    // PDF/A replaces translucent colors with opaque ones and uses native PDF dashes.
    if (const auto* writer = dynamic_cast<const QPdfWriter*>(painter->device())) {
        return writer->pdfVersion() != QPagedPaintDevice::PdfVersion_A1b;
    }
    if (const auto* printer = dynamic_cast<const QPrinter*>(painter->device())) {
        return printer->pdfVersion() != QPagedPaintDevice::PdfVersion_A1b;
    }
    return false;
}

}  // namespace

QGCustomPath::QGCustomPath(QGraphicsItem* parent)
    : QGraphicsPathItem(parent)
{}

void QGCustomPath::paint(QPainter* painter, const QStyleOptionGraphicsItem* option, QWidget* widget)
{
    const QPen pathPen = pen();
    // Qt's PDF stroker emits an unmatched close/fill when a dashed outline has no ink.
    // The public stroker matches its positive-width, noncosmetic branch; cosmetic and
    // widths below 0.0001 use different PDF transforms/normalization. Retain fills,
    // opaque-pen native dashes, background strokes and emulated perspective painting.
    if (brush().style() == Qt::NoBrush && pathPen.brush().style() == Qt::SolidPattern
        && !pathPen.brush().isOpaque() && pathPen.style() > Qt::SolidLine && !pathPen.isCosmetic()
        && pathPen.widthF() >= 0.0001 && painter->backgroundMode() == Qt::TransparentMode
        && painter->worldTransform().isAffine() && supportsTransparentPdf(painter)
        && QPainterPathStroker(pathPen).createStroke(path()).isEmpty()) {
        return;
    }
    QGraphicsPathItem::paint(painter, option, widget);
}

}  // namespace TechDrawGui
