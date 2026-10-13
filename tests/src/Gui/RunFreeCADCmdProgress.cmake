# SPDX-License-Identifier: LGPL-2.1-or-later

foreach(_variable FREECADCMD PROBE_SCRIPT PROBE_MODULE_DIR TEST_CONFIG_ROOT)
    if(NOT DEFINED ${_variable})
        message(FATAL_ERROR "${_variable} must be set")
    endif()
endforeach()
string(RANDOM LENGTH 12 ALPHABET 0123456789abcdef _suffix)
set(_config_dir "${TEST_CONFIG_ROOT}/${_suffix}")
file(MAKE_DIRECTORY "${_config_dir}")
execute_process(
    COMMAND "${FREECADCMD}" --safe-mode
        -P "${PROBE_MODULE_DIR}"
        --user-cfg "${_config_dir}/user.cfg"
        --system-cfg "${_config_dir}/system.cfg"
        "${PROBE_SCRIPT}"
    RESULT_VARIABLE _result OUTPUT_VARIABLE _stdout ERROR_VARIABLE _stderr
    TIMEOUT 25 WORKING_DIRECTORY "${_config_dir}"
)
file(REMOVE_RECURSE "${_config_dir}")
set(_output "${_stdout}\n${_stderr}")
if(NOT _result STREQUAL "0" OR _output MATCHES "Traceback|AssertionError|Not detached all observers yet")
    message(FATAL_ERROR "Progress lifecycle probe failed (${_result}).\n${_output}")
endif()
foreach(_marker
    FREECAD_SHORT_PROGRESS_CURSOR_DEFERRED
    FREECAD_LONG_NESTED_PROGRESS_CURSOR_RESTORED
    FREECAD_PROGRESS_SUCCESSOR_TIMER_RETAINED
    FREECAD_PROGRESS_WORKER_COMPLETION_RETAINED
    FREECAD_PROGRESS_WORKER_CURSOR_RETAINED
    FREECAD_SHORT_PROGRESS_CANCELLATION_RETAINED
    FREECAD_PROGRESS_EVENT_DELIVERY_RETAINED
    FREECAD_PROGRESS_HOST_CURSOR_RESTORED)
    if(NOT _output MATCHES "${_marker}")
        message(FATAL_ERROR "Progress probe did not emit ${_marker}.\n${_output}")
    endif()
endforeach()
