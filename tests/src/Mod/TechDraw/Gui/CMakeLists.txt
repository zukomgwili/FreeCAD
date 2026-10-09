# SPDX-License-Identifier: LGPL-2.1-or-later

setup_qt_test(QGCustomRect)
target_sources(QGCustomRect_Tests_run PRIVATE
    ${CMAKE_SOURCE_DIR}/src/Mod/TechDraw/Gui/QGCustomRect.cpp)
target_compile_definitions(QGCustomRect_Tests_run PRIVATE TechDrawGui_EXPORTS)

setup_qt_test(QGCustomPath)
target_sources(QGCustomPath_Tests_run PRIVATE
    ${CMAKE_SOURCE_DIR}/src/Mod/TechDraw/Gui/QGCustomPath.cpp)
target_compile_definitions(QGCustomPath_Tests_run PRIVATE TechDrawGui_EXPORTS)

setup_qt_test(QGIView)
target_sources(QGIView_Tests_run PRIVATE
    ${CMAKE_SOURCE_DIR}/src/Mod/TechDraw/Gui/QGIViewProvider.cpp)
target_compile_definitions(QGIView_Tests_run PRIVATE TechDrawGui_EXPORTS)
