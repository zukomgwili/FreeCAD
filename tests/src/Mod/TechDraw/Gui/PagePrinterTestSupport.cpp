// SPDX-License-Identifier: LGPL-2.1-or-later

// Non-installed native test bridge. It calls the production printing paths without
// a platform printer dialog; it is not part of the TechDrawGui Python API.
#include <Python.h>
#include <QPrinter>

#include <App/Document.h>
#include <App/DocumentPy.h>
#include <Base/Exception.h>
#include <Gui/Application.h>
#include <Gui/Document.h>
#include <Mod/TechDraw/App/DrawPage.h>
#include <Mod/TechDraw/App/DrawTemplate.h>
#include <Mod/TechDraw/Gui/PagePrinter.h>
#include <Mod/TechDraw/Gui/QGSPage.h>

namespace
{
App::Document* parseDocument(PyObject* object)
{
    return static_cast<App::DocumentPy*>(object)->getDocumentPtr();
}

TechDrawGui::ViewProviderPage* pageProvider(App::Document* doc, const char* name)
{
    auto* object = doc->getObject(name);
    return dynamic_cast<TechDrawGui::ViewProviderPage*>(
        Gui::Application::Instance->getViewProvider(object)
    );
}

PyObject* printPages(PyObject*, PyObject* args)
{
    PyObject* document;
    const char* path;
    int mode;
    const char* name = "";
    if (!PyArg_ParseTuple(args, "O!si|s", &App::DocumentPy::Type, &document, &path, &mode, &name)) {
        return nullptr;
    }
    try {
        auto* doc = parseDocument(document);
        QPrinter printer(QPrinter::HighResolution);
        printer.setOutputFormat(QPrinter::PdfFormat);
        printer.setOutputFileName(QString::fromUtf8(path));
        printer.setFullPage(true);
        printer.setResolution(150);
        switch (mode) {
            case 0:
                TechDrawGui::PagePrinter::printAllPdf(&printer, doc);
                break;
            case 1:
                TechDrawGui::PagePrinter::printAll(&printer, doc);
                break;
            case 2:
                TechDrawGui::PagePrinter::print(pageProvider(doc, name), &printer);
                break;
            case 3: {
                TechDrawGui::QGSPage* scene = nullptr;
                TechDrawGui::QGITemplate* pageTemplate = nullptr;
                auto restoreRendering = TechDrawGui::PagePrinter::preRenderSetUp(
                    pageProvider(doc, name),
                    scene,
                    pageTemplate
                );
                // Fault injection at the real preparation/render boundary.
                throw Base::RuntimeError("Injected render failure");
            }
            case 4: {
                auto* provider = pageProvider(doc, name);
                auto* graphics = provider->getQTemplate();
                auto* model = graphics->getTemplate();
                auto* wrongModel = dynamic_cast<TechDraw::DrawTemplate*>(
                    doc->getObject("WrongGraphicsModel")
                );
                if (!wrongModel) {
                    throw Base::RuntimeError("Expected the incompatible graphics-model fixture");
                }
                Base::ScopeGuard restoreBinding([graphics, model]() { graphics->setTemplate(model); });
                graphics->setTemplate(wrongModel);
                // The real SVG graphics template now throws from updateView,
                // inside printPdf's preparation, without throwing through Qt paint.
                TechDrawGui::PagePrinter::printPdf(provider, path);
                break;
            }
            default:
                throw Base::RuntimeError("Unknown native print test mode");
        }
        Py_RETURN_NONE;
    }
    catch (Base::Exception& e) {
        e.setPyException();
        return nullptr;
    }
    catch (const std::exception& e) {
        PyErr_SetString(PyExc_RuntimeError, e.what());
        return nullptr;
    }
}

PyObject* state(PyObject*, PyObject* args)
{
    PyObject* document;
    const char* name;
    if (!PyArg_ParseTuple(args, "O!s", &App::DocumentPy::Type, &document, &name)) {
        return nullptr;
    }
    auto* provider = pageProvider(parseDocument(document), name);
    auto* pageTemplate = provider->getQTemplate();
    return Py_BuildValue(
        "is",
        provider->getQGSPage()->getExportingPdf(),
        pageTemplate ? pageTemplate->metaObject()->className() : ""
    );
}

PyObject* setExporting(PyObject*, PyObject* args)
{
    PyObject* document;
    const char* name;
    int exporting;
    if (!PyArg_ParseTuple(args, "O!si", &App::DocumentPy::Type, &document, &name, &exporting)) {
        return nullptr;
    }
    pageProvider(parseDocument(document), name)->getQGSPage()->setExportingPdf(exporting != 0);
    Py_RETURN_NONE;
}

PyObject* setGraphicsTemplate(PyObject*, PyObject* args)
{
    PyObject* document;
    const char* pageName;
    const char* templateName;
    if (!PyArg_ParseTuple(args, "O!ss", &App::DocumentPy::Type, &document, &pageName, &templateName)) {
        return nullptr;
    }
    try {
        auto* doc = parseDocument(document);
        auto* pageTemplate = dynamic_cast<TechDraw::DrawTemplate*>(doc->getObject(templateName));
        if (!pageTemplate) {
            throw Base::RuntimeError("Expected a drawing template");
        }
        pageProvider(doc, pageName)->getQGSPage()->setPageTemplate(pageTemplate);
        Py_RETURN_NONE;
    }
    catch (Base::Exception& error) {
        error.setPyException();
        return nullptr;
    }
}

PyMethodDef methods[] = {
    {"print_pages", printPages, METH_VARARGS, "Call production native printing."},
    {"state", state, METH_VARARGS, "Inspect the actual scene export state and template type."},
    {"set_exporting", setExporting, METH_VARARGS, "Set a nested export-state control."},
    {"set_graphics_template",
     setGraphicsTemplate,
     METH_VARARGS,
     "Qualify the real non-SVG graphics-template interface on a valid page."},
    {nullptr, nullptr, 0, nullptr}
};
PyModuleDef module = {
    PyModuleDef_HEAD_INIT,
    "_PagePrinterTestSupport",
    nullptr,
    -1,
    methods,
    nullptr,
    nullptr,
    nullptr,
    nullptr
};
}  // namespace

PyMODINIT_FUNC PyInit__PagePrinterTestSupport()
{
    return PyModule_Create(&module);
}
