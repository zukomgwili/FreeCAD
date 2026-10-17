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
setup_qt_test(ProgressBarReset)
if(APPLE)
    setup_qt_test(CocoaSaveSheet)
    set_tests_properties(CocoaSaveSheet_Tests_run PROPERTIES TIMEOUT 20)
endif()

# FreeCADCmd can create the GUI lazily through FreeCADGui.showMainWindow().
# Keep this as a separate process because the relevant failure occurs during
# application shutdown.
if(BUILD_GUI)
    if(BUILD_TEST)
        add_test(NAME FreeCADGuiTestExitStatus
            COMMAND ${Python3_EXECUTABLE}
                "${CMAKE_SOURCE_DIR}/tests/src/App/TestRunnerExitStatus.py"
                --executable $<TARGET_FILE:FreeCADMain> --gui)
        set_tests_properties(FreeCADGuiTestExitStatus PROPERTIES
            ENVIRONMENT "QT_QPA_PLATFORM=offscreen" LABELS "Qt;Process" TIMEOUT 450)
        if(APPLE)
            # Cocoa can dispatch QApplication::quit immediately; offscreen alone
            # does not reproduce a failure status lost during native shutdown.
            set_tests_properties(FreeCADGuiTestExitStatus PROPERTIES
                ENVIRONMENT "QT_QPA_PLATFORM=cocoa" LABELS "Qt;NativeGui;Process"
                RESOURCE_LOCK FreeCADNativeGui)
        endif()
        if(WIN32)
            set_tests_properties(FreeCADGuiTestExitStatus PROPERTIES
                ENVIRONMENT_MODIFICATION "${_test_env_mod}")
        endif()
    endif()

    # Test-only access to the native progress controller; never installed.
    add_library(ProgressBarTestSupport MODULE ProgressBarTestSupport.cpp)
    target_include_directories(ProgressBarTestSupport PRIVATE
        ${CMAKE_SOURCE_DIR}/src ${CMAKE_BINARY_DIR}/src ${CMAKE_BINARY_DIR}
        ${Python3_INCLUDE_DIRS})
    target_link_libraries(ProgressBarTestSupport PRIVATE FreeCADApp FreeCADGui
        ${Python3_LIBRARIES})
    set_target_properties(ProgressBarTestSupport PROPERTIES PREFIX ""
        OUTPUT_NAME "_ProgressBarTestSupport"
        LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/tests/GuiNative"
        RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/tests/GuiNative")
    if(WIN32)
        set_target_properties(ProgressBarTestSupport PROPERTIES SUFFIX ".pyd")
    else()
        set_target_properties(ProgressBarTestSupport PROPERTIES SUFFIX ".so")
    endif()
    add_test(NAME FreeCADCmdProgress
        COMMAND ${CMAKE_COMMAND}
            "-DFREECADCMD=$<TARGET_FILE:FreeCADMainCmd>"
            "-DPROBE_SCRIPT=${CMAKE_CURRENT_SOURCE_DIR}/FreeCADCmdProgress.py"
            "-DPROBE_MODULE_DIR=$<TARGET_FILE_DIR:ProgressBarTestSupport>"
            "-DTEST_CONFIG_ROOT=${CMAKE_CURRENT_BINARY_DIR}/FreeCADCmdProgress"
            -P "${CMAKE_CURRENT_SOURCE_DIR}/RunFreeCADCmdProgress.cmake")
    set_tests_properties(FreeCADCmdProgress PROPERTIES
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen" LABELS "Qt;Process" TIMEOUT 30)
    if(WIN32)
        set_property(TEST FreeCADCmdProgress PROPERTY
            ENVIRONMENT_MODIFICATION "${_test_env_mod}")
    endif()
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

    foreach(_lazy_gui_mode synchronous threaded-rejected threaded-recovery host-application without-gui)
        add_test(
            NAME FreeCADCmdLazyGui-${_lazy_gui_mode}
            COMMAND ${CMAKE_COMMAND}
                "-DFREECADCMD=$<TARGET_FILE:FreeCADMainCmd>"
                "-DPROBE_SCRIPT=${CMAKE_CURRENT_SOURCE_DIR}/FreeCADCmdLazyGui.py"
                "-DTEST_CONFIG_ROOT=${_freecadcmd_gui_shutdown_config_dir}"
                "-DTEST_MODE=${_lazy_gui_mode}"
                -P "${CMAKE_CURRENT_SOURCE_DIR}/RunFreeCADCmdLazyGui.cmake"
        )
        set_tests_properties(
            FreeCADCmdLazyGui-${_lazy_gui_mode}
            PROPERTIES
                ENVIRONMENT "QT_QPA_PLATFORM=offscreen"
                LABELS "Qt;Process"
                TIMEOUT 30
        )
        if(WIN32)
            set_property(
                TEST FreeCADCmdLazyGui-${_lazy_gui_mode}
                PROPERTY ENVIRONMENT_MODIFICATION "${_test_env_mod}"
            )
        endif()
    endforeach()

    set(_freecadcmd_notification_area_reentry_config_dir
        "${CMAKE_CURRENT_BINARY_DIR}/FreeCADCmdNotificationAreaReentry")

    add_test(
        NAME FreeCADCmdNotificationAreaReentry
        COMMAND ${CMAKE_COMMAND}
            "-DFREECADCMD=$<TARGET_FILE:FreeCADMainCmd>"
            "-DPROBE_SCRIPT=${CMAKE_CURRENT_SOURCE_DIR}/NotificationAreaReentry.py"
            "-DTEST_CONFIG_ROOT=${_freecadcmd_notification_area_reentry_config_dir}"
            -P "${CMAKE_CURRENT_SOURCE_DIR}/RunFreeCADCmdNotificationAreaReentry.cmake"
    )
    set_tests_properties(
        FreeCADCmdNotificationAreaReentry
        PROPERTIES
            ENVIRONMENT "QT_QPA_PLATFORM=offscreen"
            LABELS "Qt;Process"
            TIMEOUT 20
    )

    if(WIN32)
        set_property(
            TEST FreeCADCmdNotificationAreaReentry
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

if(BUILD_GUI)
    setup_qt_test(NotificationBoxLifetime)
    target_sources(NotificationBoxLifetime_Tests_run PRIVATE
        ${CMAKE_SOURCE_DIR}/src/Gui/NotificationBox.cpp)
    target_compile_definitions(NotificationBoxLifetime_Tests_run PRIVATE FreeCADGui_EXPORTS)

    # This native widget-lifetime bridge is test-only and never installed.
    add_library(NotificationBoxTestSupport MODULE NotificationBoxTestSupport.cpp)
    target_include_directories(NotificationBoxTestSupport PRIVATE
        ${CMAKE_SOURCE_DIR}/src ${CMAKE_BINARY_DIR}/src ${CMAKE_BINARY_DIR}
        ${Python3_INCLUDE_DIRS})
    target_link_libraries(NotificationBoxTestSupport PRIVATE FreeCADApp FreeCADGui
        ${Python3_LIBRARIES})
    set_target_properties(NotificationBoxTestSupport PROPERTIES PREFIX ""
        OUTPUT_NAME "_NotificationBoxTestSupport"
        LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/tests/GuiNative"
        RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/tests/GuiNative")
    if(WIN32)
        set_target_properties(NotificationBoxTestSupport PROPERTIES SUFFIX ".pyd")
    else()
        set_target_properties(NotificationBoxTestSupport PROPERTIES SUFFIX ".so")
    endif()
    add_test(NAME NotificationBoxNativeShutdown
        COMMAND $<TARGET_FILE:FreeCADMain>
            -P "${CMAKE_CURRENT_SOURCE_DIR}"
            -P "$<TARGET_FILE_DIR:NotificationBoxTestSupport>"
            -u "${CMAKE_CURRENT_BINARY_DIR}/notification-box-user.cfg"
            -s "${CMAKE_CURRENT_BINARY_DIR}/notification-box-system.cfg"
            -t NotificationBoxShutdownTest)
    set_tests_properties(NotificationBoxNativeShutdown PROPERTIES LABELS "NativeGui"
        RESOURCE_LOCK FreeCADNativeGui
        TIMEOUT 30
        PASS_REGULAR_EXPRESSION "NATIVE_NOTIFICATION_DESTROYED_WITH_APPLICATION"
        FAIL_REGULAR_EXPRESSION "FAILED;FAIL:;ERROR:")
endif()
