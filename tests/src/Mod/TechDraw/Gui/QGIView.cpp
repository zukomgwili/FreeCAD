// SPDX-License-Identifier: LGPL-2.1-or-later

#include <QTest>

#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <src/App/InitApplication.h>

#include <Gui/Application.h>

#include <Mod/TechDraw/Gui/QGIView.h>

class QGIViewTest: public QObject
{
    Q_OBJECT

private Q_SLOTS:
    void viewProviderIsNullWhenGuiApplicationIsUnavailable()
    {
        tests::initApplication();

        const std::string documentName =
            App::GetApplication().getUniqueDocumentName("QGIViewTest");
        App::Document* document =
            App::GetApplication().newDocument(documentName.c_str(), "QGIViewTest");
        App::DocumentObject* object = document->addObject("App::FeaturePython", "View");

        QVERIFY(Gui::Application::Instance == nullptr);
        QVERIFY(TechDrawGui::QGIView::getViewProvider(object) == nullptr);

        App::GetApplication().closeDocument(documentName.c_str());
    }

    void viewProviderIsNullWhenGuiDocumentIsUnavailable()
    {
        tests::initApplication();

        const std::string documentName =
            App::GetApplication().getUniqueDocumentName("QGIViewTest");
        App::Document* document =
            App::GetApplication().newDocument(documentName.c_str(), "QGIViewTest");
        App::DocumentObject* object = document->addObject("App::FeaturePython", "View");

        if (!Gui::Application::Instance) {
            new Gui::Application(false);
        }

        QVERIFY(Gui::Application::Instance->getDocument(document) == nullptr);
        QVERIFY(TechDrawGui::QGIView::getViewProvider(object) == nullptr);

        App::GetApplication().closeDocument(documentName.c_str());
    }
};

QTEST_MAIN(QGIViewTest)
#include "QGIView.moc"
