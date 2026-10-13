// SPDX-License-Identifier: LGPL-2.1-or-later

// Non-installed bridge to the native progress controller. Python's public
// progress indicator does not expose the main-thread abort/pause callbacks.
#include <Python.h>

#include <Gui/ProgressBar.h>

namespace
{
PyObject* checkAbort(PyObject*, PyObject*)
{
    Gui::SequencerBar::instance()->checkAbort();
    Py_RETURN_NONE;
}

PyObject* pauseResume(PyObject*, PyObject*)
{
    auto* sequencer = Gui::SequencerBar::instance();
    sequencer->pause();
    sequencer->resume();
    Py_RETURN_NONE;
}

PyMethodDef methods[] = {
    {"check_abort", checkAbort, METH_NOARGS, "Check native progress cancellation."},
    {"pause_resume", pauseResume, METH_NOARGS, "Pause and resume native progress."},
    {nullptr, nullptr, 0, nullptr}
};
PyModuleDef module = {
    PyModuleDef_HEAD_INIT,
    "_ProgressBarTestSupport",
    nullptr,
    -1,
    methods,
    nullptr,
    nullptr,
    nullptr,
    nullptr
};
}  // namespace

PyMODINIT_FUNC PyInit__ProgressBarTestSupport()
{
    return PyModule_Create(&module);
}
