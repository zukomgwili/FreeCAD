import unittest
import Materials


class ArrayNullWitness(unittest.TestCase):
    def test_native_empty_cell_is_not_authored_zero(self):
        array = Materials.Array2D()
        array.Columns = 1
        array.Rows = 1
        null_value = array.getValue(0, 0)
        array.setValue(0, 0, "0")
        authored_zero = array.getValue(0, 0)
        print("[DEBUG-3sc] native-resized-empty", repr(null_value),
              "authored-zero", repr(authored_zero))
        self.assertNotEqual(null_value, authored_zero,
                            "Native empty cell and authored zero must remain distinguishable")
