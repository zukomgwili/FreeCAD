# SPDX-License-Identifier: LGPL-2.1-or-later

cmake_minimum_required(VERSION 3.21)
project(QtPdfStrokerQualification LANGUAGES CXX)

find_package(Qt6 REQUIRED COMPONENTS Core Gui)
option(WITH_QPRINTER "Exercise QPrinter PDF output in addition to QPdfWriter" OFF)
add_executable(qt_pdf_stroker_fixture generator.cpp)
target_compile_features(qt_pdf_stroker_fixture PRIVATE cxx_std_17)
target_link_libraries(qt_pdf_stroker_fixture PRIVATE Qt6::Core Qt6::Gui)
target_link_libraries(qt_pdf_stroker_fixture PRIVATE ${CMAKE_DL_LIBS})
if(WITH_QPRINTER)
    find_package(Qt6 REQUIRED COMPONENTS PrintSupport)
    target_link_libraries(qt_pdf_stroker_fixture PRIVATE Qt6::PrintSupport)
    target_compile_definitions(qt_pdf_stroker_fixture PRIVATE WITH_QPRINTER)
endif()
