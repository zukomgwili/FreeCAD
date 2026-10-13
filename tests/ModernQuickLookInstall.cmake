# SPDX-License-Identifier: LGPL-2.1-or-later

foreach(_required FREECAD_SOURCE_DIR TEST_ROOT)
    if(NOT DEFINED ${_required})
        message(FATAL_ERROR "${_required} must be set")
    endif()
endforeach()

# Keep both possible installation destinations in a new disposable directory.
# Exercise the actual install rules without compiling or registering Swift code.
string(RANDOM LENGTH 12 ALPHABET 0123456789abcdef _suffix)
set(_run_root "${TEST_ROOT}/quicklook-routing-${_suffix}")
set(_source_dir "${_run_root}/source")
set(_build_dir "${_run_root}/build")
set(_configured_prefix "${_run_root}/configured-prefix")
set(_stage_prefix "${_run_root}/stage-prefix")
file(MAKE_DIRECTORY "${_source_dir}")
file(WRITE "${_source_dir}/CMakeLists.txt" [=[
cmake_minimum_required(VERSION 3.22)
project(ModernQuickLookInstallRouting LANGUAGES NONE)
set(CMAKE_OSX_DEPLOYMENT_TARGET "15.0")
add_subdirectory("${FREECAD_SOURCE_DIR}/src/MacAppBundle/QuickLook/modern"
    "${CMAKE_CURRENT_BINARY_DIR}/modern")
]=])

execute_process(
    COMMAND "${CMAKE_COMMAND}" -S "${_source_dir}" -B "${_build_dir}"
        "-DFREECAD_SOURCE_DIR=${FREECAD_SOURCE_DIR}"
        "-DCMAKE_INSTALL_PREFIX=${_configured_prefix}"
    RESULT_VARIABLE _configure_result
    OUTPUT_VARIABLE _configure_stdout
    ERROR_VARIABLE _configure_stderr
)
if(NOT _configure_result STREQUAL "0")
    message(FATAL_ERROR
        "QuickLook routing fixture configuration failed (${_configure_result}).\n"
        "${_configure_stdout}\n${_configure_stderr}")
endif()

set(_extensions FreeCADThumbnailExtension FreeCADPreviewExtension)
foreach(_extension IN LISTS _extensions)
    set(_payload_relative "PlugIns/${_extension}.appex/Contents/Resources/install-routing.txt")
    set(_payload_source
        "${_build_dir}/src/MacAppBundle/FreeCAD.app/Contents/${_payload_relative}")
    set(_sentinel_path
        "${_configured_prefix}/PlugIns/${_extension}.appex/Contents/Resources/configured-prefix-sentinel.txt")
    get_filename_component(_payload_directory "${_payload_source}" DIRECTORY)
    get_filename_component(_sentinel_directory "${_sentinel_path}" DIRECTORY)
    file(MAKE_DIRECTORY "${_payload_directory}" "${_sentinel_directory}")
    file(WRITE "${_payload_source}" "New ${_extension} payload\n")
    file(WRITE "${_sentinel_path}" "Preserve ${_extension} configured-prefix sentinel\n")
endforeach()

execute_process(
    COMMAND "${CMAKE_COMMAND}" --install "${_build_dir}"
        --prefix "${_stage_prefix}" --component ModernQuickLook
    RESULT_VARIABLE _install_result
    OUTPUT_VARIABLE _install_stdout
    ERROR_VARIABLE _install_stderr
)
if(NOT _install_result STREQUAL "0")
    message(FATAL_ERROR
        "QuickLook routing fixture install failed (${_install_result}).\n"
        "${_install_stdout}\n${_install_stderr}")
endif()

foreach(_extension IN LISTS _extensions)
    set(_payload_relative "PlugIns/${_extension}.appex/Contents/Resources/install-routing.txt")
    file(READ
        "${_configured_prefix}/PlugIns/${_extension}.appex/Contents/Resources/configured-prefix-sentinel.txt"
        _sentinel)
    if(NOT _sentinel STREQUAL "Preserve ${_extension} configured-prefix sentinel\n")
        message(FATAL_ERROR
            "${_extension} modified the configured prefix despite the staging --prefix.\n"
            "${_install_stdout}\n${_install_stderr}")
    endif()
    if(EXISTS "${_configured_prefix}/${_payload_relative}")
        message(FATAL_ERROR
            "${_extension} wrote its payload into the configured prefix despite --prefix.\n"
            "${_install_stdout}\n${_install_stderr}")
    endif()
    if(NOT EXISTS "${_stage_prefix}/${_payload_relative}")
        message(FATAL_ERROR "${_extension} was not installed under the staging prefix")
    endif()
    file(READ "${_stage_prefix}/${_payload_relative}" _payload)
    if(NOT _payload STREQUAL "New ${_extension} payload\n")
        message(FATAL_ERROR "${_extension} staged payload did not match the source")
    endif()
endforeach()

file(REMOVE_RECURSE "${_run_root}")
message(STATUS "Both ModernQuickLook extensions obey --prefix; configured prefix unchanged")
