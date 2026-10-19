# SPDX-License-Identifier: LGPL-2.1-or-later
"""Tree/property-editor presentation for saved contact-side observations."""

from FreeCAD import Qt

from femviewprovider.view_base_femobject import VPBaseFemObject


class VPContactObservation(VPBaseFemObject):
    def getIcon(self):
        return ":/icons/FEM_PostFilterDataAtPoint.svg"

    def setupContextMenu(self, vobj, menu):
        action = menu.addAction(
            Qt.translate("FEM_ResultContactObservation", "Refresh contact-side observations")
        )
        action.triggered.connect(lambda _checked=False: self.refresh(vobj))

    def refresh(self, vobj):
        """Revalidate through the result's public action, not a display cache."""
        obj = vobj.Object
        doc = obj.Document
        doc.openTransaction("Refresh contact-side observations")
        try:
            obj.Proxy.refresh(obj)
            doc.commitTransaction()
        except Exception:
            doc.abortTransaction()
            raise
