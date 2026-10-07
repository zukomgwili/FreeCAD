# Copyright (C) 2022 The Qt Company Ltd.
# SPDX-License-Identifier: BSD-3-Clause
# Source list follows qtbase 6.11.2 src/plugins/platforms/cocoa/CMakeLists.txt
# (Copyright The Qt Company Ltd., SPDX-License-Identifier: BSD-3-Clause).
# This builds only the Cocoa platform plugin; it has no install target.
cmake_minimum_required(VERSION 3.20)
project(FreeCADCocoaPlugin LANGUAGES CXX OBJCXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_OBJCXX_STANDARD 17)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
if(NOT APPLE OR NOT CMAKE_OSX_ARCHITECTURES STREQUAL "arm64")
    message(FATAL_ERROR "This overlay is qualified only for macOS arm64")
endif()
if(NOT CMAKE_OSX_DEPLOYMENT_TARGET STREQUAL "11.0")
    message(FATAL_ERROR "The Cocoa overlay must retain the baseline deployment target 11.0")
endif()
if(NOT IS_DIRECTORY "${FREECAD_COCOA_QT_PREFIX}" OR
   NOT IS_DIRECTORY "${FREECAD_COCOA_DEPENDENCY_INCLUDE}")
    message(FATAL_ERROR "Select the exact installed Qt prefix and pinned Vulkan headers")
endif()
# Pin each package entry point; no system Qt or source-tree private headers.
foreach(package Qt6 Qt6Core Qt6Gui Qt6CorePrivate Qt6GuiPrivate Qt6CoreTools Qt6GuiTools)
    set(${package}_DIR "${FREECAD_COCOA_QT_PREFIX}/lib/cmake/${package}" CACHE PATH "" FORCE)
endforeach()
find_package(Qt6 6.11.2 EXACT REQUIRED COMPONENTS Core Gui)
find_package(Qt6CorePrivate 6.11.2 EXACT REQUIRED)
find_package(Qt6GuiPrivate 6.11.2 EXACT REQUIRED)
add_library(QCocoaIntegrationPlugin MODULE
    cocoa/main.mm
    cocoa/qnsview.mm
    cocoa/qcocoavulkaninstance.mm
    cocoa/qcocoaapplication.h
    cocoa/qcocoaapplication.mm
    cocoa/qcocoaapplicationdelegate.h
    cocoa/qcocoaapplicationdelegate.mm
    cocoa/qcocoabackingstore.h
    cocoa/qcocoabackingstore.mm
    cocoa/qcocoaclipboard.h
    cocoa/qcocoaclipboard.mm
    cocoa/qcocoacursor.h
    cocoa/qcocoacursor.mm
    cocoa/qcocoadrag.h
    cocoa/qcocoadrag.mm
    cocoa/qcocoaeventdispatcher.h
    cocoa/qcocoaeventdispatcher.mm
    cocoa/qcocoahelpers.h
    cocoa/qcocoahelpers.mm
    cocoa/qcocoainputcontext.h
    cocoa/qcocoainputcontext.mm
    cocoa/qcocoaintegration.h
    cocoa/qcocoaintegration.mm
    cocoa/qcocoaintrospection.h
    cocoa/qcocoaintrospection.mm
    cocoa/qcocoamenu.h
    cocoa/qcocoamenu.mm
    cocoa/qcocoamenubar.h
    cocoa/qcocoamenubar.mm
    cocoa/qcocoamenuitem.h
    cocoa/qcocoamenuitem.mm
    cocoa/qcocoamenuloader.h
    cocoa/qcocoamenuloader.mm
    cocoa/qcocoamimetypes.h
    cocoa/qcocoamimetypes.mm
    cocoa/qcocoanativeinterface.h
    cocoa/qcocoanativeinterface.mm
    cocoa/qcocoansmenu.h
    cocoa/qcocoansmenu.mm
    cocoa/qcocoascreen.h
    cocoa/qcocoascreen.mm
    cocoa/qcocoaservices.h
    cocoa/qcocoaservices.mm
    cocoa/qcocoasystemtrayicon.h
    cocoa/qcocoasystemtrayicon.mm
    cocoa/qcocoatheme.h
    cocoa/qcocoatheme.mm
    cocoa/qcocoawindow.h
    cocoa/qcocoawindow.mm
    cocoa/qcocoawindowmanager.h
    cocoa/qcocoawindowmanager.mm
    cocoa/qiosurfacegraphicsbuffer.h
    cocoa/qiosurfacegraphicsbuffer.mm
    cocoa/qmacclipboard.h
    cocoa/qmacclipboard.mm
    cocoa/qmultitouch_mac.mm
    cocoa/qmultitouch_mac_p.h
    cocoa/qnsview.h
    cocoa/qnswindow.h
    cocoa/qnswindow.mm
    cocoa/qnswindowdelegate.h
    cocoa/qnswindowdelegate.mm
    cocoa/qcocoacolordialoghelper.h
    cocoa/qcocoacolordialoghelper.mm
    cocoa/qcocoafiledialoghelper.h
    cocoa/qcocoafiledialoghelper.mm
    cocoa/qcocoafontdialoghelper.h
    cocoa/qcocoafontdialoghelper.mm
    cocoa/qcocoamessagedialog.h
    cocoa/qcocoamessagedialog.mm
    cocoa/qcocoaglcontext.h
    cocoa/qcocoaglcontext.mm
    cocoa/qcocoaaccessibility.h
    cocoa/qcocoaaccessibility.mm
    cocoa/qcocoaaccessibilityelement.h
    cocoa/qcocoaaccessibilityelement.mm
    cocoa/qcocoasessionmanager.cpp
    cocoa/qcocoasessionmanager.h
    qcocoaresources.qrc)
set_target_properties(QCocoaIntegrationPlugin PROPERTIES
    OUTPUT_NAME qcocoa SUFFIX .dylib
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/platforms"
    BUILD_RPATH "${FREECAD_COCOA_QT_PREFIX}/lib"
    INSTALL_RPATH "@loader_path/../../..")
target_include_directories(QCocoaIntegrationPlugin PRIVATE cocoa)
target_compile_definitions(QCocoaIntegrationPlugin PRIVATE QT_PLUGIN)
target_link_libraries(QCocoaIntegrationPlugin PRIVATE Qt6::CorePrivate Qt6::GuiPrivate)
target_link_libraries(QCocoaIntegrationPlugin PRIVATE "-framework Foundation")
target_link_libraries(QCocoaIntegrationPlugin PRIVATE "-framework AppKit")
target_link_libraries(QCocoaIntegrationPlugin PRIVATE "-framework Carbon")
target_link_libraries(QCocoaIntegrationPlugin PRIVATE "-framework CoreServices")
target_link_libraries(QCocoaIntegrationPlugin PRIVATE "-framework CoreVideo")
target_link_libraries(QCocoaIntegrationPlugin PRIVATE "-framework IOKit")
target_link_libraries(QCocoaIntegrationPlugin PRIVATE "-framework IOSurface")
target_link_libraries(QCocoaIntegrationPlugin PRIVATE "-framework Metal")
target_link_libraries(QCocoaIntegrationPlugin PRIVATE "-framework QuartzCore")
target_link_libraries(QCocoaIntegrationPlugin PRIVATE "-framework UniformTypeIdentifiers")
target_link_libraries(QCocoaIntegrationPlugin PRIVATE "-framework OpenGL")

target_include_directories(QCocoaIntegrationPlugin PRIVATE
    "${FREECAD_COCOA_DEPENDENCY_INCLUDE}")
# Preserve the exact libraries selected by the imported private Qt targets.
file(GENERATE OUTPUT "${CMAKE_BINARY_DIR}/qt-targets.json" CONTENT
    "{\"Qt6::Core\":\"$<TARGET_FILE:Qt6::Core>\",\"Qt6::Gui\":\"$<TARGET_FILE:Qt6::Gui>\",\"Qt6::moc\":\"$<TARGET_FILE:Qt6::moc>\",\"Qt6::rcc\":\"$<TARGET_FILE:Qt6::rcc>\"}\n")
