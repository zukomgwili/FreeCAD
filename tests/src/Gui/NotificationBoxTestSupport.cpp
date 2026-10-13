// SPDX-License-Identifier: LGPL-2.1-or-later

// Non-installed bridge: inspect native widgets without Python Qt wrappers
// changing their lifetime, and exercise the ordinary native console API.
#include <Python.h>
#include <QApplication>
#include <QThread>
#include <QWidget>
#include <cstdio>

#include <Base/Console.h>

namespace
{
PyObject* emitError(PyObject*, PyObject*)
{
    Base::Console().error("Native notification shutdown regression\n");
    Py_RETURN_NONE;
}

PyObject* observePopup(PyObject*, PyObject*)
{
    for (auto* widget : QApplication::topLevelWidgets()) {
        if (widget->inherits("Gui::NotificationLabel") && widget->isVisible()) {
            QObject::connect(widget, &QObject::destroyed, qApp, []() {
                // A qApp connection context cannot run after its destruction.
                // Also require the GUI thread while Qt's thread services live.
                if (QCoreApplication::instance()
                    && QThread::currentThread() == QCoreApplication::instance()->thread()) {
                    std::fprintf(stdout, "NATIVE_NOTIFICATION_DESTROYED_WITH_APPLICATION\n");
                    std::fflush(stdout);
                }
            });
            Py_RETURN_TRUE;
        }
    }
    Py_RETURN_FALSE;
}

PyMethodDef methods[] = {
    {"emit_error", emitError, METH_NOARGS, "Emit an ordinary native console error."},
    {"observe_popup",
     observePopup,
     METH_NOARGS,
     "Require a real popup and record destruction while the Qt application lives."},
    {nullptr, nullptr, 0, nullptr}
};
PyModuleDef module = {
    PyModuleDef_HEAD_INIT,
    "_NotificationBoxTestSupport",
    nullptr,
    -1,
    methods,
    nullptr,
    nullptr,
    nullptr,
    nullptr
};
}  // namespace

PyMODINIT_FUNC PyInit__NotificationBoxTestSupport()
{
    return PyModule_Create(&module);
}
