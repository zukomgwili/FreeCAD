// SPDX-License-Identifier: LGPL-2.1-or-later

#include <QApplication>
#include <QEvent>
#include <QMetaObject>
#include <QTest>
#include <QWidget>

#include <Gui/ProgressBar.h>

class PaintCounter: public QObject
{
public:
    int count {0};

protected:
    bool eventFilter(QObject*, QEvent* event) override
    {
        if (event->type() == QEvent::Paint) {
            ++count;
        }
        return false;
    }
};

class ProgressBarResetTest: public QObject
{
    Q_OBJECT

private Q_SLOTS:
    void completedProgressDoesNotSynchronouslyRepaint()
    {
        QWidget window;
        auto* bar = Gui::SequencerBar::instance()->getProgressBar(&window);
        QCOMPARE(static_cast<Gui::ProgressBar*>(bar)->minimumDuration(), 2000);
        bar->setRange(0, 100);
        bar->setValue(50);
        bar->resize(120, 30);
        PaintCounter paints;
        bar->installEventFilter(&paints);
        window.show();
        bar->show();
        QTest::qWait(20);
        bar->repaint();
        QVERIFY(paints.count > 0);  // Reject an unexposed/ineffective paint fixture.
        paints.count = 0;

        QVERIFY(QMetaObject::invokeMethod(bar, "resetEx", Qt::DirectConnection));

        QCOMPARE(paints.count, 0);
        QVERIFY(bar->isHidden());
        QCOMPARE(bar->value(), bar->minimum() - 1);
        bar->removeEventFilter(&paints);
    }
};

QTEST_MAIN(ProgressBarResetTest)
#include "ProgressBarReset.moc"
