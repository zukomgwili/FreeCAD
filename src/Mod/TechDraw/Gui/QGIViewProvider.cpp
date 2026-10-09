// SPDX-License-Identifier: LGPL-2.1-or-later

#include <App/DocumentObject.h>
#include <Gui/Application.h>
#include <Gui/Document.h>

#include "QGIView.h"

using namespace TechDrawGui;

/* static */
Gui::ViewProvider* QGIView::getViewProvider(App::DocumentObject* obj)
{
    if (!obj || !Gui::Application::Instance) {
        return nullptr;
    }

    Gui::Document* guiDoc = Gui::Application::Instance->getDocument(obj->getDocument());
    return guiDoc ? guiDoc->getViewProvider(obj) : nullptr;
}
