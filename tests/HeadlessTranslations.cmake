# SPDX-License-Identifier: LGPL-2.1-or-later

foreach(_required FREECAD_SOURCE_DIR TEST_ROOT TEST_QT_MAJOR TEST_CXX_COMPILER)
    if(NOT DEFINED ${_required})
        message(FATAL_ERROR "${_required} must be set")
    endif()
endforeach()

string(RANDOM LENGTH 12 ALPHABET 0123456789abcdef _suffix)
set(_run_root "${TEST_ROOT}/headless-translations-${_suffix}")
set(_source "${_run_root}/source")
set(_build "${_run_root}/build")
file(MAKE_DIRECTORY "${_source}/src")
configure_file("${FREECAD_SOURCE_DIR}/src/QtWidgets.h.cmake"
    "${_source}/src/QtWidgets.h.cmake" COPYONLY)
file(WRITE "${_source}/tiny.ts" [=[
<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="de"><context><name>Headless</name>
<message><source>Hello</source><translation>Hallo</translation></message>
</context></TS>
]=])
file(WRITE "${_source}/CMakeLists.txt" [=[
cmake_minimum_required(VERSION 3.22)
project(HeadlessTranslations LANGUAGES CXX)
set(BUILD_GUI OFF)
set(ENABLE_DEVELOPER_TESTS OFF)
set(FREECAD_QT_MAJOR_VERSION "${TEST_QT_MAJOR}")
include("${FREECAD_SOURCE_DIR}/cMake/FreeCAD_Helpers/SetupQt.cmake")
qt_find_and_add_translation(_qm "${CMAKE_CURRENT_SOURCE_DIR}/tiny.ts"
    "${CMAKE_CURRENT_BINARY_DIR}")
add_custom_target(translations ALL DEPENDS ${_qm})
]=])

execute_process(
    COMMAND "${CMAKE_COMMAND}" -S "${_source}" -B "${_build}"
        "-DFREECAD_SOURCE_DIR=${FREECAD_SOURCE_DIR}"
        "-DTEST_QT_MAJOR=${TEST_QT_MAJOR}"
        "-DCMAKE_CXX_COMPILER=${TEST_CXX_COMPILER}"
        "-DCMAKE_PREFIX_PATH=${CMAKE_PREFIX_PATH}"
    RESULT_VARIABLE _configured
    OUTPUT_VARIABLE _stdout ERROR_VARIABLE _stderr
)
if(NOT _configured STREQUAL "0")
    message(FATAL_ERROR "Headless translation configure failed:\n${_stdout}\n${_stderr}")
endif()
execute_process(
    COMMAND "${CMAKE_COMMAND}" --build "${_build}" --target translations
    RESULT_VARIABLE _built
    OUTPUT_VARIABLE _stdout ERROR_VARIABLE _stderr
)
if(NOT _built STREQUAL "0")
    message(FATAL_ERROR "Headless translation build failed:\n${_stdout}\n${_stderr}")
endif()
if(NOT EXISTS "${_build}/tiny.qm")
    message(FATAL_ERROR "Headless translation target did not create tiny.qm")
endif()
file(SIZE "${_build}/tiny.qm" _size)
if(_size EQUAL 0)
    message(FATAL_ERROR "Headless translation output is empty")
endif()
file(REMOVE_RECURSE "${_run_root}")
message(STATUS "Headless Qt discovery compiles a nonempty translation catalog")
