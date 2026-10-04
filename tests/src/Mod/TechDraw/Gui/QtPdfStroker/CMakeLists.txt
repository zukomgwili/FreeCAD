# SPDX-License-Identifier: LGPL-2.1-or-later

cmake_minimum_required(VERSION 3.21)
project(QtPdfStrokerQualification LANGUAGES CXX)

find_package(Qt6 REQUIRED COMPONENTS Core Gui)
add_executable(qt_pdf_stroker_fixture generator.cpp)
target_compile_features(qt_pdf_stroker_fixture PRIVATE cxx_std_17)
target_link_libraries(qt_pdf_stroker_fixture PRIVATE Qt6::Core Qt6::Gui)
