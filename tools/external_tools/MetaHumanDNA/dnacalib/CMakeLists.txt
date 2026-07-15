cmake_minimum_required(VERSION 3.14)
project(dnacalib)

# >>> Force Maya's Python
set(PYTHON_EXECUTABLE "C:/Program Files/Autodesk/Maya2023/bin/mayapy.exe")
set(Python_EXECUTABLE "${PYTHON_EXECUTABLE}")
set(Python3_EXECUTABLE "${PYTHON_EXECUTABLE}")
# <<<

list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_LIST_DIR}/CMakeModulesExtra")

enable_testing()

add_subdirectory(DNACalib)
add_subdirectory(SPyUS)
add_subdirectory(PyDNA)
add_subdirectory(PyDNACalib)

################################################
# Package build artifacts
set(CPACK_GENERATOR "ZIP")
set(CPACK_ARCHIVE_COMPONENT_INSTALL ON)
set(CPACK_COMPONENT_INCLUDE_TOPLEVEL_DIRECTORY OFF)
set(CPACK_COMPONENTS_GROUPING ALL_COMPONENTS_IN_ONE)
string(CONCAT CPACK_PACKAGE_FILE_NAME "${CMAKE_PROJECT_NAME}"
                                      "-${CMAKE_PROJECT_VERSION}"
                                      "-${CMAKE_SYSTEM_NAME}"
                                      "-${CMAKE_SYSTEM_PROCESSOR}"
                                      "-${CMAKE_CXX_COMPILER_ID}${CMAKE_CXX_COMPILER_VERSION}"
                                      "-${CMAKE_BUILD_TYPE}"
                                      "-${PYTHON3_EXACT_VERSION}"
                                      "-SHARED")
include(CPack)
