// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <QGraphicsPathItem>
#include <Mod/TechDraw/TechDrawGlobal.h>

namespace TechDrawGui
{

class TechDrawGuiExport QGCustomPath: public QGraphicsPathItem
{
public:
    explicit QGCustomPath(QGraphicsItem* parent = nullptr);
    void paint(QPainter* painter, const QStyleOptionGraphicsItem* option, QWidget* widget = nullptr) override;
};

}  // namespace TechDrawGui
