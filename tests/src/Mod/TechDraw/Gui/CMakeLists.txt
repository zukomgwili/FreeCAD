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

# This bridge is only built for native integration tests, never installed.
add_library(PagePrinterTestSupport MODULE PagePrinterTestSupport.cpp)
target_include_directories(PagePrinterTestSupport PRIVATE
    ${CMAKE_SOURCE_DIR}/src
    ${CMAKE_SOURCE_DIR}/src/Mod/TechDraw/Gui
    ${CMAKE_BINARY_DIR}/src
    ${CMAKE_BINARY_DIR}/src/Mod/TechDraw/Gui
    ${CMAKE_BINARY_DIR}
    ${Python3_INCLUDE_DIRS})
target_link_libraries(PagePrinterTestSupport PRIVATE TechDrawGui FreeCADApp FreeCADGui
    ${Python3_LIBRARIES} ${QtPrintSupport_LIBRARIES})
set_target_properties(PagePrinterTestSupport PROPERTIES
    PREFIX ""
    OUTPUT_NAME "_PagePrinterTestSupport"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/tests/TechDrawNative"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/tests/TechDrawNative")
if(WIN32)
    set_target_properties(PagePrinterTestSupport PROPERTIES SUFFIX ".pyd")
else()
    set_target_properties(PagePrinterTestSupport PROPERTIES SUFFIX ".so")
endif()
add_test(NAME PagePrinterNative
    COMMAND $<TARGET_FILE:FreeCADMain>
        -P "${CMAKE_CURRENT_SOURCE_DIR}"
        -P "$<TARGET_FILE_DIR:PagePrinterTestSupport>"
        -u "${CMAKE_CURRENT_BINARY_DIR}/page-printer-user.cfg"
        -s "${CMAKE_CURRENT_BINARY_DIR}/page-printer-system.cfg"
        -t PagePrinterTest)
set_tests_properties(PagePrinterNative PROPERTIES LABELS "NativeGui"
    RESOURCE_LOCK FreeCADNativeGui
    TIMEOUT 120
    PASS_REGULAR_EXPRESSION "OK"
    FAIL_REGULAR_EXPRESSION "FAILED;FAIL:;ERROR:")
