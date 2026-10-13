# SPDX-License-Identifier: LGPL-2.1-or-later

foreach(_required_variable FREECADCMD PROBE_SCRIPT TEST_CONFIG_ROOT)
    if(NOT DEFINED ${_required_variable})
        message(FATAL_ERROR "${_required_variable} must be set")
    endif()
endforeach()

string(RANDOM LENGTH 12 ALPHABET 0123456789abcdef _config_suffix)
set(_config_dir "${TEST_CONFIG_ROOT}/${_config_suffix}")
file(MAKE_DIRECTORY "${_config_dir}")

execute_process(
    COMMAND "${FREECADCMD}"
        --safe-mode
        --user-cfg "${_config_dir}/user.cfg"
        --system-cfg "${_config_dir}/system.cfg"
        "${PROBE_SCRIPT}"
    RESULT_VARIABLE _result
    OUTPUT_VARIABLE _stdout
    ERROR_VARIABLE _stderr
    TIMEOUT 15
    WORKING_DIRECTORY "${_config_dir}"
)

file(REMOVE_RECURSE "${_config_dir}")

if(NOT _result STREQUAL "0")
    message(FATAL_ERROR
        "FreeCADCmd exited with ${_result}.\nstdout:\n${_stdout}\nstderr:\n${_stderr}"
    )
endif()

set(_output "${_stdout}\n${_stderr}")
foreach(
    _marker
    FREECAD_NOTIFICATION_REENTRY_OUTER_RETURNED
    FREECAD_NOTIFICATION_REENTRY_BOUNDARY
    FREECAD_NOTIFICATION_REENTRY_NESTED_RETURNED
    FREECAD_NOTIFICATION_REENTRY_COMPLETED
)
    string(FIND "${_output}" "${_marker}" _marker_position)
    if(_marker_position EQUAL -1)
        message(FATAL_ERROR "FreeCADCmd did not emit ${_marker}.\n${_output}")
    endif()
endforeach()
