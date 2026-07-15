#----------------------------------------------------------------
# Generated CMake target import file for configuration "Release".
#----------------------------------------------------------------

# Commands may need to know the format version.
set(CMAKE_IMPORT_FILE_VERSION 1)

# Import target "DNACalib::dnacalib" for configuration "Release"
set_property(TARGET DNACalib::dnacalib APPEND PROPERTY IMPORTED_CONFIGURATIONS RELEASE)
set_target_properties(DNACalib::dnacalib PROPERTIES
  IMPORTED_LINK_INTERFACE_LANGUAGES_RELEASE "CXX"
  IMPORTED_LOCATION_RELEASE "${_IMPORT_PREFIX}/lib/dnacalib.lib"
  )

list(APPEND _cmake_import_check_targets DNACalib::dnacalib )
list(APPEND _cmake_import_check_files_for_DNACalib::dnacalib "${_IMPORT_PREFIX}/lib/dnacalib.lib" )

# Commands beyond this point should not need to know the version.
set(CMAKE_IMPORT_FILE_VERSION)
