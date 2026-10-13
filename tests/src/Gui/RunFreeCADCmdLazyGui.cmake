# SPDX-License-Identifier: LGPL-2.1-or-later

foreach(_required_variable FREECADCMD PROBE_SCRIPT TEST_CONFIG_ROOT TEST_MODE)
    if(NOT DEFINED ${_required_variable})
        message(FATAL_ERROR "${_required_variable} must be set")
    endif()
endforeach()

string(RANDOM LENGTH 12 ALPHABET 0123456789abcdef _config_suffix)
set(_config_dir "${TEST_CONFIG_ROOT}/${_config_suffix}")
file(MAKE_DIRECTORY "${_config_dir}")

execute_process(
    COMMAND "${CMAKE_COMMAND}" -E env "FREECAD_LAZY_GUI_TEST_MODE=${TEST_MODE}"
        "${FREECADCMD}"
        --safe-mode
        --user-cfg "${_config_dir}/user.cfg"
        --system-cfg "${_config_dir}/system.cfg"
        "${PROBE_SCRIPT}"
    RESULT_VARIABLE _result
    OUTPUT_VARIABLE _stdout
    ERROR_VARIABLE _stderr
    TIMEOUT 25
    WORKING_DIRECTORY "${_config_dir}"
)

file(REMOVE_RECURSE "${_config_dir}")
set(_output "${_stdout}\n${_stderr}")
if(NOT _result STREQUAL "0")
    message(FATAL_ERROR "FreeCADCmd exited with ${_result}.\n${_output}")
endif()
if(_output MATCHES "Traceback|AssertionError|Not detached all observers yet")
    message(FATAL_ERROR "FreeCADCmd lazy GUI lifecycle failed.\n${_output}")
endif()

if(TEST_MODE STREQUAL "threaded-rejected")
    set(_markers FREECADCMD_THREADED_GUI_REJECTED)
elseif(TEST_MODE STREQUAL "without-gui")
    set(_markers
        FREECADCMD_LAZY_SERVICES_INITIALIZED
        FREECADCMD_LAZY_GUI_DOCUMENT_DESTROYED
    )
else()
    set(_markers
        FREECADCMD_LAZY_GUI_INITIALIZED
        FREECADCMD_LAZY_GUI_WINDOW_DESTROYED
        FREECADCMD_LAZY_GUI_PARAMETERS_AVAILABLE
    )
endif()
foreach(_marker IN LISTS _markers)
    string(FIND "${_output}" "${_marker}" _marker_position)
    if(_marker_position EQUAL -1)
        message(FATAL_ERROR "FreeCADCmd did not emit ${_marker}.\n${_output}")
    endif()
endforeach()
