// SPDX-License-Identifier: LGPL-2.1-or-later

#include <QApplication>
#include <QPointer>
#include <QSignalSpy>
#include <QTest>
#include <QWidget>

#include <Gui/NotificationBox.h>

class NotificationBoxLifetime: public QObject
{
    Q_OBJECT

    static QWidget* popup()
    {
        for (auto* widget : QApplication::topLevelWidgets()) {
            if (widget->objectName() == QStringLiteral("NotificationBox_label")) {
                return widget;
            }
        }
        return nullptr;
    }

private Q_SLOTS:
    void cleanup()
    {
        Gui::NotificationBox::destroy();
        QCoreApplication::sendPostedEvents(nullptr, QEvent::DeferredDelete);
    }

    void destroysSynchronouslyWhileApplicationLives()
    {
        Gui::NotificationBox::showText(QPoint(50, 50), QStringLiteral("Shutdown popup"));
        QPointer<QWidget> widget = popup();
        QVERIFY(widget);
        QSignalSpy destroyed(widget, &QObject::destroyed);
        bool applicationAliveAtDestruction = false;
        QObject::connect(widget, &QObject::destroyed, [&applicationAliveAtDestruction]() {
            applicationAliveAtDestruction = QCoreApplication::instance() != nullptr;
        });
        Gui::NotificationBox::destroy();
        QVERIFY(widget.isNull());
        QCOMPARE(destroyed.count(), 1);
        QVERIFY(applicationAliveAtDestruction);
        QVERIFY(!Gui::NotificationBox::isVisible());
        QVERIFY(Gui::NotificationBox::text().isEmpty());
        // Empty destruction is harmless, including service-only GUI shutdown.
        Gui::NotificationBox::destroy();
    }

    void canRecreateAfterDestruction()
    {
        Gui::NotificationBox::showText(QPoint(50, 50), QStringLiteral("First popup"));
        QPointer<QWidget> first = popup();
        QVERIFY(first);
        Gui::NotificationBox::destroy();
        QVERIFY(first.isNull());
        Gui::NotificationBox::showText(QPoint(50, 50), QStringLiteral("Second popup"));
        QVERIFY(popup());
        QVERIFY(Gui::NotificationBox::isVisible());
        QCOMPARE(Gui::NotificationBox::text(), QStringLiteral("Second popup"));
    }

    void pendingHideTimerCannotRetireNewPopup()
    {
        Gui::NotificationBox::showText(QPoint(50, 50), QStringLiteral("Old timed popup"));
        Gui::NotificationBox::hideText();
        Gui::NotificationBox::destroy();
        Gui::NotificationBox::showText(QPoint(50, 50), QStringLiteral("New popup"));
        QTest::qWait(350);
        QVERIFY(Gui::NotificationBox::isVisible());
        QCOMPARE(Gui::NotificationBox::text(), QStringLiteral("New popup"));
    }
};

QTEST_MAIN(NotificationBoxLifetime)
#include "NotificationBoxLifetime.moc"
