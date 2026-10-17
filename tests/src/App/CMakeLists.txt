# SPDX-License-Identifier: LGPL-2.1-or-later

add_executable(App_tests_run
        AsyncRecompute.cpp
        Application.cpp
        ApplicationDirectories.cpp
        BackupPolicy.cpp
        Branding.cpp
        ComplexGeoData.cpp
        Document.cpp
        DocumentObject.cpp
        DocumentObserver.cpp
        Expression.cpp
        ExpressionParser.cpp
        QuantityInput.cpp
        ElementMap.cpp
        ElementNamingUtils.cpp
        IndexedName.cpp
        License.cpp
        Link.cpp
        MappedElement.cpp
        MappedName.cpp
        Metadata.cpp
        ProjectFile.cpp
        PropertyFile.cpp
        Property.h
        Property.cpp
        PropertyExpressionEngine.cpp
        StringHasher.cpp
        VarSet.cpp
        VRMLObject.cpp
)

target_compile_definitions(App_tests_run PRIVATE DATADIR="${CMAKE_SOURCE_DIR}/data")

target_link_libraries(App_tests_run PRIVATE
    GTest::gmock_main
    ${Python3_LIBRARIES}
    FreeCADApp
)

# A separate shared-runtime Python host reaches MainPy's real import entrypoint;
# FreeCADCmd has already initialized FreeCAD before it executes Python scripts.
add_executable(FreeCAD_EmbeddingHost EmbeddingHost.cpp)
target_include_directories(FreeCAD_EmbeddingHost PRIVATE ${Python3_INCLUDE_DIRS})
target_link_libraries(FreeCAD_EmbeddingHost PRIVATE ${Python3_LIBRARIES})
set_target_properties(FreeCAD_EmbeddingHost PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/tests")
add_dependencies(FreeCAD_EmbeddingHost FreeCADMainPy FreeCADMainCmd)
add_test(NAME FreeCAD_EmbeddingRuntime
    COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/EmbeddingRuntime.py"
        --host $<TARGET_FILE:FreeCAD_EmbeddingHost>
        --module-dir $<TARGET_FILE_DIR:FreeCADMainPy>
        --freecadcmd $<TARGET_FILE:FreeCADMainCmd>)
set_tests_properties(FreeCAD_EmbeddingRuntime PROPERTIES LABELS "App;Embedding")
if(WIN32)
    set_tests_properties(FreeCAD_EmbeddingRuntime PROPERTIES
        ENVIRONMENT_MODIFICATION "${_test_env_mod}")
endif()

if(BUILD_TEST)
    add_test(NAME FreeCADCmdTestExitStatus
        COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/TestRunnerExitStatus.py"
            --executable $<TARGET_FILE:FreeCADMainCmd>)
    set_tests_properties(FreeCADCmdTestExitStatus PROPERTIES LABELS "App;Process" TIMEOUT 510)
    if(WIN32)
        set_tests_properties(FreeCADCmdTestExitStatus PROPERTIES
            ENVIRONMENT_MODIFICATION "${_test_env_mod}")
    endif()
endif()
