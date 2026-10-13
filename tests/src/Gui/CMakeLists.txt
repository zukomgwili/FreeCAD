# SPDX-License-Identifier: LGPL-2.1-or-later

add_subdirectory(Dialogs)
add_subdirectory(propertyeditor)

# Standard C++ GTest tests
add_executable(Gui_tests_run
        Assistant.cpp
        Camera.cpp
        ColorScaleOverlayTest.cpp
        FileDialog.cpp
        StyleParameters/DiagnosticsCapture.h
        StyleParameters/ValueMatchers.h
        StyleParameters/ValueMatchers.cpp
        StyleParameters/StyleParametersApplicationTest.cpp
        StyleParameters/ParserTest.cpp
        StyleParameters/ParserRobustnessTest.cpp
        StyleParameters/ParameterManagerTest.cpp
        StyleParameters/YamlParameterSourceTest.cpp
        StyleParameters/DiagnosticsTest.cpp
        StyleParameters/ValueAccessTest.cpp
        StyleParameters/EdgesTest.cpp
        StyleParameters/CornersTest.cpp
        StyleParameters/GradientTest.cpp
        StyleParameters/ColorShadingTest.cpp
        InputHintTest.cpp
        ViewProviderDoubleClick.cpp
        NativeGesturePinchTest.cpp
        NavigationStylePinchTest.cpp
        NavigationStyleWheelTest.cpp
        SelectionTest.cpp
        SoMouseWheelEventTest.cpp
)

# Qt tests
setup_qt_test(ObjectSelection)
setup_qt_test(TranslatorLocale)
setup_qt_test(InputField)
setup_qt_test(QuantitySpinBox)
setup_qt_test(NumericLocaleConsumers)

# FreeCADCmd can create the GUI lazily through FreeCADGui.showMainWindow().
# Keep this as a separate process because the relevant failure occurs during
# application shutdown.
if(BUILD_GUI)
    set(_freecadcmd_gui_shutdown_config_dir
        "${CMAKE_CURRENT_BINARY_DIR}/FreeCADCmdGuiShutdown")

    add_test(
        NAME FreeCADCmdGuiShutdown
        COMMAND ${CMAKE_COMMAND}
            "-DFREECADCMD=$<TARGET_FILE:FreeCADMainCmd>"
            "-DPROBE_SCRIPT=${CMAKE_CURRENT_SOURCE_DIR}/FreeCADCmdGuiShutdown.py"
            "-DTEST_CONFIG_ROOT=${_freecadcmd_gui_shutdown_config_dir}"
            -P "${CMAKE_CURRENT_SOURCE_DIR}/RunFreeCADCmdGuiShutdown.cmake"
    )
    set_tests_properties(
        FreeCADCmdGuiShutdown
        PROPERTIES
            ENVIRONMENT "QT_QPA_PLATFORM=offscreen"
            LABELS "Qt;Process"
            TIMEOUT 30
    )

    if(WIN32)
        set_property(
            TEST FreeCADCmdGuiShutdown
            PROPERTY ENVIRONMENT_MODIFICATION "${_test_env_mod}"
        )
    endif()
endif()

target_link_libraries(Gui_tests_run PRIVATE
    GTest::gmock_main
    FreeCADApp
    FreeCADGui
)

if(WIN32)
    target_compile_definitions(Gui_tests_run PRIVATE QUARTER_DLL)
endif()
