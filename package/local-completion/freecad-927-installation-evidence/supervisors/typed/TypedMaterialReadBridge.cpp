// Private read-only witness bridge: do not change the editor's data.
#include <QStandardItem>
#include <QVariant>
#include <Mod/Material/App/Materials.h>
#include <Mod/Material/App/MaterialPy.h>

extern "C" PyObject* copy_editor_item_material(QStandardItem* item)
{
    const auto material = item->data().value<std::shared_ptr<Materials::Material>>();
    if (!material) {
        PyErr_SetString(PyExc_RuntimeError, "Editor item has no native material");
        return nullptr;
    }
    return new Materials::MaterialPy(new Materials::Material(*material));
}
