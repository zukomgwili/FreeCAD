# SPDX-License-Identifier: LGPL-2.1-or-later

setup_qt_test(QGCustomRect)
target_sources(QGCustomRect_Tests_run PRIVATE
    ${CMAKE_SOURCE_DIR}/src/Mod/TechDraw/Gui/QGCustomRect.cpp)
target_compile_definitions(QGCustomRect_Tests_run PRIVATE TechDrawGui_EXPORTS)
