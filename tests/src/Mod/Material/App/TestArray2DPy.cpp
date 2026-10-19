// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <initializer_list>
#include <limits>
#include <memory>
#include <string>
#include <utility>

#include <QByteArray>
#include <QMetaType>
#include <QString>
#include <QStringList>
#include <QVariant>

#include <App/Application.h>
#include <Base/Interpreter.h>
#include <Base/Quantity.h>
#include <Base/QuantityPy.h>
#include <src/App/InitApplication.h>

#include <Mod/Material/App/Array2DPy.h>
#include <Mod/Material/App/MaterialValue.h>

namespace
{

class TestArray2DPy: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        if (App::Application::GetARGC() == 0) {
            tests::initApplication();
        }
    }

    void SetUp() override
    {
        gil = PyGILState_Ensure();
        Base::Interpreter().runString("import Materials");
    }

    void TearDown() override
    {
        PyErr_Clear();
        PyGILState_Release(gil);
    }

    static Py::Object wrap(std::initializer_list<QVariant> cells)
    {
        auto array = std::make_unique<Materials::Array2D>();
        array->setColumns(static_cast<int>(cells.size()));
        array->setRows(1);
        int column = 0;
        for (const auto& cell : cells) {
            array->setValue(0, column++, cell);
        }
        return Py::Object(new Materials::Array2DPy(array.release()), true);
    }

    PyGILState_STATE gil {};
};

TEST_F(TestArray2DPy, TypedArrayRetainsNullQuantityUnitsAndPrecision)
{
    const Base::Quantity zero(0.0);
    const Base::Quantity precise(123.45678901234567, Base::Unit::Length);
    const auto wrapper = wrap({QVariant(), QVariant::fromValue(zero), QVariant::fromValue(precise)});
    PyObject* raw = PyObject_GetAttrString(wrapper.ptr(), "TypedArray");
    ASSERT_NE(raw, nullptr) << "The public TypedArray accessor must be available";
    const Py::List typed(raw, true);
    ASSERT_EQ(typed.size(), 1);
    const Py::List row(typed[0]);
    ASSERT_EQ(row.size(), 3);
    EXPECT_EQ(row[0].ptr(), Py_None);
    ASSERT_TRUE(PyObject_TypeCheck(row[1].ptr(), &Base::QuantityPy::Type));
    ASSERT_TRUE(PyObject_TypeCheck(row[2].ptr(), &Base::QuantityPy::Type));
    const auto* storedZero = static_cast<Base::QuantityPy*>(row[1].ptr())->getQuantityPtr();
    const auto* storedPrecise = static_cast<Base::QuantityPy*>(row[2].ptr())->getQuantityPtr();
    EXPECT_EQ(*storedZero, zero);
    EXPECT_DOUBLE_EQ(storedPrecise->getValue(), precise.getValue());
    EXPECT_EQ(storedPrecise->getUnit(), precise.getUnit());
}

TEST_F(TestArray2DPy, TypedArrayRetainsNativeNumericAndBooleanValues)
{
    const double precise = 0.12345678901234567;
    const float single = 0.123456789F;
    const qlonglong signedWide = -(Q_INT64_C(1) << 55) + 13;
    const qulonglong unsignedWide = (Q_UINT64_C(1) << 63) + 29;
    const long signedLong = std::numeric_limits<long>::max() - 17;
    const unsigned long unsignedLong = std::numeric_limits<unsigned long>::max() - 19;
    const auto wrapper = wrap(
        {QVariant::fromValue(precise),
         QVariant::fromValue(single),
         QVariant::fromValue(-173),
         QVariant::fromValue(std::numeric_limits<unsigned int>::max()),
         QVariant::fromValue(signedWide),
         QVariant::fromValue(unsignedWide),
         QVariant::fromValue(signedLong),
         QVariant::fromValue(unsignedLong),
         QVariant::fromValue(true),
         QVariant::fromValue(false)}
    );
    PyObject* raw = PyObject_GetAttrString(wrapper.ptr(), "TypedArray");
    ASSERT_NE(raw, nullptr);
    const Py::List typed(raw, true);
    const Py::List row(typed[0]);
    ASSERT_EQ(row.size(), 10);
    ASSERT_TRUE(PyFloat_CheckExact(row[0].ptr()));
    ASSERT_TRUE(PyFloat_CheckExact(row[1].ptr()));
    EXPECT_DOUBLE_EQ(PyFloat_AsDouble(row[0].ptr()), precise);
    EXPECT_DOUBLE_EQ(PyFloat_AsDouble(row[1].ptr()), static_cast<double>(single));
    for (Py_ssize_t column = 2; column < 8; ++column) {
        EXPECT_TRUE(PyLong_CheckExact(row[column].ptr())) << column;
    }
    EXPECT_EQ(PyLong_AsLong(row[2].ptr()), -173);
    EXPECT_EQ(PyLong_AsUnsignedLong(row[3].ptr()), std::numeric_limits<unsigned int>::max());
    EXPECT_EQ(PyLong_AsLongLong(row[4].ptr()), signedWide);
    EXPECT_EQ(PyLong_AsUnsignedLongLong(row[5].ptr()), unsignedWide);
    EXPECT_EQ(PyLong_AsLong(row[6].ptr()), signedLong);
    EXPECT_EQ(PyLong_AsUnsignedLong(row[7].ptr()), unsignedLong);
    EXPECT_EQ(row[8].ptr(), Py_True);
    EXPECT_EQ(row[9].ptr(), Py_False);
    EXPECT_EQ(PyErr_Occurred(), nullptr);
}

TEST_F(TestArray2DPy, TypedArrayRetainsNarrowIntegerMetaTypes)
{
    const char character = std::numeric_limits<char>::min() + 1;
    const signed char signedCharacter = -101;
    const unsigned char unsignedCharacter = 251;
    const short signedShort = -32701;
    const unsigned short unsignedShort = std::numeric_limits<unsigned short>::max();
    const auto wrapper = wrap(
        {QVariant::fromValue(character),
         QVariant::fromValue(signedCharacter),
         QVariant::fromValue(unsignedCharacter),
         QVariant::fromValue(signedShort),
         QVariant::fromValue(unsignedShort)}
    );
    PyObject* raw = PyObject_GetAttrString(wrapper.ptr(), "TypedArray");
    ASSERT_NE(raw, nullptr);
    const Py::List typed(raw, true);
    const Py::List row(typed[0]);
    ASSERT_EQ(row.size(), 5);
    for (Py_ssize_t column = 0; column < row.size(); ++column) {
        EXPECT_TRUE(PyLong_CheckExact(row[column].ptr())) << column;
    }
    EXPECT_EQ(PyLong_AsLong(row[0].ptr()), character);
    EXPECT_EQ(PyLong_AsLong(row[1].ptr()), signedCharacter);
    EXPECT_EQ(PyLong_AsUnsignedLong(row[2].ptr()), unsignedCharacter);
    EXPECT_EQ(PyLong_AsLong(row[3].ptr()), signedShort);
    EXPECT_EQ(PyLong_AsUnsignedLong(row[4].ptr()), unsignedShort);
    EXPECT_EQ(PyErr_Occurred(), nullptr);
}

TEST_F(TestArray2DPy, TypedArrayDistinguishesTypedNullVariantsFromAuthoredZero)
{
    const QVariant nullFloat(QMetaType::fromType<float>());
    const QVariant nullDouble(QMetaType::fromType<double>());
    const QVariant nullInt(QMetaType::fromType<int>());
    const QVariant nullBoolean(QMetaType::fromType<bool>());
    const QVariant nullString(QMetaType::fromType<QString>());
    for (const auto& cell : {nullFloat, nullDouble, nullInt, nullBoolean, nullString}) {
        ASSERT_TRUE(cell.isValid());
        ASSERT_TRUE(cell.isNull());
    }
    const auto wrapper = wrap(
        {nullFloat,
         nullDouble,
         nullInt,
         nullBoolean,
         nullString,
         QVariant::fromValue(0.0F),
         QVariant::fromValue(0.0),
         QVariant::fromValue(0),
         QVariant::fromValue(false),
         QVariant::fromValue(QStringLiteral("")),
         QVariant::fromValue(Base::Quantity(0.0))}
    );
    PyObject* raw = PyObject_GetAttrString(wrapper.ptr(), "TypedArray");
    ASSERT_NE(raw, nullptr);
    const Py::List typed(raw, true);
    const Py::List row(typed[0]);
    ASSERT_EQ(row.size(), 11);
    for (Py_ssize_t column = 0; column < 5; ++column) {
        EXPECT_EQ(row[column].ptr(), Py_None) << column;
    }
    for (Py_ssize_t column = 5; column < 7; ++column) {
        ASSERT_TRUE(PyFloat_CheckExact(row[column].ptr())) << column;
        EXPECT_DOUBLE_EQ(PyFloat_AsDouble(row[column].ptr()), 0.0);
    }
    ASSERT_TRUE(PyLong_CheckExact(row[7].ptr()));
    EXPECT_EQ(PyLong_AsLong(row[7].ptr()), 0);
    EXPECT_EQ(row[8].ptr(), Py_False);
    ASSERT_TRUE(PyUnicode_CheckExact(row[9].ptr()));
    EXPECT_EQ(PyUnicode_GetLength(row[9].ptr()), 0);
    ASSERT_TRUE(PyObject_TypeCheck(row[10].ptr(), &Base::QuantityPy::Type));
    EXPECT_EQ(*static_cast<Base::QuantityPy*>(row[10].ptr())->getQuantityPtr(), Base::Quantity(0.0));
}

TEST_F(TestArray2DPy, TypedArrayRetainsUnicodeAndEmbeddedNull)
{
    const QString text = QString::fromUtf8("Grüße λ") + QChar(u'\0') + QStringLiteral("after");
    const auto expected = text.toUtf8();
    const auto wrapper = wrap({QVariant::fromValue(text), QVariant::fromValue(QStringLiteral(""))});
    PyObject* raw = PyObject_GetAttrString(wrapper.ptr(), "TypedArray");
    ASSERT_NE(raw, nullptr);
    const Py::List typed(raw, true);
    const Py::List row(typed[0]);
    ASSERT_TRUE(PyUnicode_CheckExact(row[0].ptr()));
    ASSERT_TRUE(PyUnicode_CheckExact(row[1].ptr()));
    Py_ssize_t length = 0;
    const char* utf8 = PyUnicode_AsUTF8AndSize(row[0].ptr(), &length);
    ASSERT_NE(utf8, nullptr);
    EXPECT_EQ(length, expected.size());
    EXPECT_EQ(std::string(utf8, static_cast<std::size_t>(length)), expected.toStdString());
    EXPECT_EQ(PyUnicode_GetLength(row[1].ptr()), 0);
}

TEST_F(TestArray2DPy, TypedArrayRetainsSupplementaryUnicodeAndLoneSurrogates)
{
    const char16_t units[] = {u'A', 0xD83D, 0xDE80, 0xD800, u'B', 0xDC00};
    const QString text = QString::fromUtf16(units, 6);
    const auto wrapper = wrap({QVariant::fromValue(text)});
    PyObject* raw = PyObject_GetAttrString(wrapper.ptr(), "TypedArray");
    ASSERT_NE(raw, nullptr);
    const Py::List typed(raw, true);
    const Py::List row(typed[0]);
    ASSERT_TRUE(PyUnicode_CheckExact(row[0].ptr()));
    ASSERT_EQ(PyUnicode_GetLength(row[0].ptr()), 5);
    EXPECT_EQ(PyUnicode_ReadChar(row[0].ptr(), 0), static_cast<Py_UCS4>('A'));
    EXPECT_EQ(PyUnicode_ReadChar(row[0].ptr(), 1), static_cast<Py_UCS4>(0x1F680));
    EXPECT_EQ(PyUnicode_ReadChar(row[0].ptr(), 2), static_cast<Py_UCS4>(0xD800));
    EXPECT_EQ(PyUnicode_ReadChar(row[0].ptr(), 3), static_cast<Py_UCS4>('B'));
    EXPECT_EQ(PyUnicode_ReadChar(row[0].ptr(), 4), static_cast<Py_UCS4>(0xDC00));
    EXPECT_EQ(PyErr_Occurred(), nullptr);
}

TEST_F(TestArray2DPy, TypedArrayRetainsEmptyRowsAndZeroSizedShapes)
{
    for (const auto& dimensions : {std::pair(0, 7), std::pair(3, 0)}) {
        SCOPED_TRACE(::testing::Message() << dimensions.first << "x" << dimensions.second);
        auto array = std::make_unique<Materials::Array2D>();
        array->setColumns(dimensions.second);
        array->setRows(dimensions.first);
        const Py::Object wrapper(new Materials::Array2DPy(array.release()), true);
        PyObject* raw = PyObject_GetAttrString(wrapper.ptr(), "TypedArray");
        ASSERT_NE(raw, nullptr);
        const Py::List typed(raw, true);
        ASSERT_EQ(typed.size(), dimensions.first);
        for (Py_ssize_t row = 0; row < typed.size(); ++row) {
            ASSERT_TRUE(PyList_CheckExact(typed[row].ptr()));
            EXPECT_EQ(PyList_Size(typed[row].ptr()), 0);
        }
        const auto* native = static_cast<Materials::Array2DPy*>(wrapper.ptr())->getArray2DPtr();
        EXPECT_EQ(native->rows(), dimensions.first);
        EXPECT_EQ(native->columns(), dimensions.second);
    }
}

TEST_F(TestArray2DPy, TypedArrayIsReadOnlyAndReturnsIndependentCopies)
{
    const Base::Quantity original(1.2345678901234567, Base::Unit::Length);
    const auto wrapper = wrap({QVariant::fromValue(original)});
    PyObject* raw = PyObject_GetAttrString(wrapper.ptr(), "TypedArray");
    ASSERT_NE(raw, nullptr);
    const Py::List typed(raw, true);
    Py::List row(typed[0]);
    ASSERT_TRUE(PyObject_TypeCheck(row[0].ptr(), &Base::QuantityPy::Type));
    static_cast<Base::QuantityPy*>(row[0].ptr())->getQuantityPtr()->setValue(99.0);
    row.setItem(0, Py::Float(19.0));

    PyObject* rereadRaw = PyObject_GetAttrString(wrapper.ptr(), "TypedArray");
    ASSERT_NE(rereadRaw, nullptr);
    const Py::List reread(rereadRaw, true);
    const Py::List rereadRow(reread[0]);
    ASSERT_TRUE(PyObject_TypeCheck(rereadRow[0].ptr(), &Base::QuantityPy::Type));
    EXPECT_EQ(*static_cast<Base::QuantityPy*>(rereadRow[0].ptr())->getQuantityPtr(), original);
    EXPECT_EQ(PyObject_SetAttrString(wrapper.ptr(), "TypedArray", Py_None), -1);
    EXPECT_TRUE(PyErr_ExceptionMatches(PyExc_AttributeError));
    PyErr_Clear();
}

TEST_F(TestArray2DPy, TypedArrayRejectsUnsupportedNativeCellTypes)
{
    const QVariant nullBytes(QMetaType::fromType<QByteArray>());
    const QVariant nullStringList(QMetaType::fromType<QStringList>());
    ASSERT_TRUE(nullBytes.isValid() && nullBytes.isNull());
    ASSERT_TRUE(nullStringList.isValid() && nullStringList.isNull());
    for (const auto& cell : {
             QVariant::fromValue(QByteArray("not a supported scalar")),
             nullBytes,
             QVariant::fromValue(QStringList {QStringLiteral("first"), QStringLiteral("second")}),
             nullStringList,
         }) {
        SCOPED_TRACE(::testing::Message() << cell.typeName() << " null=" << cell.isNull());
        const auto wrapper = wrap({cell});
        PyObject* raw = PyObject_GetAttrString(wrapper.ptr(), "TypedArray");
        EXPECT_EQ(raw, nullptr);
        Py_XDECREF(raw);
        EXPECT_TRUE(PyErr_ExceptionMatches(PyExc_TypeError));
        PyErr_Clear();
    }
}

TEST_F(TestArray2DPy, TypedArrayRejectsMalformedNativeDimensionsAndRows)
{
    for (int malformed = 0; malformed < 3; ++malformed) {
        SCOPED_TRACE(malformed);
        auto array = std::make_unique<Materials::Array2D>();
        array->setColumns(malformed == 0 ? -1 : 2);
        if (malformed == 1) {
            array->addRow(nullptr);
        }
        else if (malformed == 2) {
            array->addRow(std::make_shared<QList<QVariant>>(QList<QVariant> {QVariant(1.0)}));
        }
        const Py::Object wrapper(new Materials::Array2DPy(array.release()), true);
        PyObject* raw = PyObject_GetAttrString(wrapper.ptr(), "TypedArray");
        EXPECT_EQ(raw, nullptr);
        Py_XDECREF(raw);
        ASSERT_NE(PyErr_Occurred(), nullptr);
        EXPECT_TRUE(PyErr_ExceptionMatches(PyExc_ValueError));
        PyErr_Clear();
    }
}

TEST_F(TestArray2DPy, LegacyQuantityCoercionRemainsCompatible)
{
    const auto wrapper = wrap({QVariant(), QVariant::fromValue(13.25)});
    PyObject* raw = PyObject_GetAttrString(wrapper.ptr(), "Array");
    ASSERT_NE(raw, nullptr);
    const Py::List legacy(raw, true);
    const Py::List row(legacy[0]);
    for (Py_ssize_t column = 0; column < 2; ++column) {
        ASSERT_TRUE(PyObject_TypeCheck(row[column].ptr(), &Base::QuantityPy::Type));
        EXPECT_EQ(
            *static_cast<Base::QuantityPy*>(row[column].ptr())->getQuantityPtr(),
            Base::Quantity()
        );
    }
    PyObject* valueRaw = PyObject_CallMethod(wrapper.ptr(), "getValue", "ii", 0, 1);
    ASSERT_NE(valueRaw, nullptr);
    const Py::Object value(valueRaw, true);
    EXPECT_TRUE(PyObject_TypeCheck(value.ptr(), &Base::QuantityPy::Type));
    EXPECT_EQ(*static_cast<Base::QuantityPy*>(value.ptr())->getQuantityPtr(), Base::Quantity());
    PyObject* rowRaw = PyObject_CallMethod(wrapper.ptr(), "getRow", "i", 0);
    ASSERT_NE(rowRaw, nullptr);
    const Py::List legacyRow(rowRaw, true);
    EXPECT_TRUE(PyObject_TypeCheck(legacyRow[1].ptr(), &Base::QuantityPy::Type));
    EXPECT_EQ(*static_cast<Base::QuantityPy*>(legacyRow[1].ptr())->getQuantityPtr(), Base::Quantity());
}

}  // namespace
