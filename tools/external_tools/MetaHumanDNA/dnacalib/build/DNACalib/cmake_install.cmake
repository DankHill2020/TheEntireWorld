# Install script for directory: C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/DNACalib

# Set the install prefix
if(NOT DEFINED CMAKE_INSTALL_PREFIX)
  set(CMAKE_INSTALL_PREFIX "C:/Program Files (x86)/dnacalib")
endif()
string(REGEX REPLACE "/$" "" CMAKE_INSTALL_PREFIX "${CMAKE_INSTALL_PREFIX}")

# Set the install configuration name.
if(NOT DEFINED CMAKE_INSTALL_CONFIG_NAME)
  if(BUILD_TYPE)
    string(REGEX REPLACE "^[^A-Za-z0-9_]+" ""
           CMAKE_INSTALL_CONFIG_NAME "${BUILD_TYPE}")
  else()
    set(CMAKE_INSTALL_CONFIG_NAME "Release")
  endif()
  message(STATUS "Install configuration: \"${CMAKE_INSTALL_CONFIG_NAME}\"")
endif()

# Set the component getting installed.
if(NOT CMAKE_INSTALL_COMPONENT)
  if(COMPONENT)
    message(STATUS "Install component: \"${COMPONENT}\"")
    set(CMAKE_INSTALL_COMPONENT "${COMPONENT}")
  else()
    set(CMAKE_INSTALL_COMPONENT)
  endif()
endif()

# Is this installation the result of a crosscompile?
if(NOT DEFINED CMAKE_CROSSCOMPILING)
  set(CMAKE_CROSSCOMPILING "FALSE")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "dnacalib" OR NOT CMAKE_INSTALL_COMPONENT)
  if(CMAKE_INSTALL_CONFIG_NAME MATCHES "^([Dd][Ee][Bb][Uu][Gg])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib" TYPE STATIC_LIBRARY FILES "C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/build/DNACalib/Debug/dnacalib.lib")
  elseif(CMAKE_INSTALL_CONFIG_NAME MATCHES "^([Rr][Ee][Ll][Ee][Aa][Ss][Ee])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib" TYPE STATIC_LIBRARY FILES "C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/build/DNACalib/Release/dnacalib.lib")
  elseif(CMAKE_INSTALL_CONFIG_NAME MATCHES "^([Mm][Ii][Nn][Ss][Ii][Zz][Ee][Rr][Ee][Ll])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib" TYPE STATIC_LIBRARY FILES "C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/build/DNACalib/MinSizeRel/dnacalib.lib")
  elseif(CMAKE_INSTALL_CONFIG_NAME MATCHES "^([Rr][Ee][Ll][Ww][Ii][Tt][Hh][Dd][Ee][Bb][Ii][Nn][Ff][Oo])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib" TYPE STATIC_LIBRARY FILES "C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/build/DNACalib/RelWithDebInfo/dnacalib.lib")
  endif()
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "dnacalib" OR NOT CMAKE_INSTALL_COMPONENT)
  if(EXISTS "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/cmake/DNACalib/DNACalibTargets.cmake")
    file(DIFFERENT _cmake_export_file_changed FILES
         "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/cmake/DNACalib/DNACalibTargets.cmake"
         "C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/build/DNACalib/CMakeFiles/Export/5c635dbe6b9c68e293e1ec21692732fa/DNACalibTargets.cmake")
    if(_cmake_export_file_changed)
      file(GLOB _cmake_old_config_files "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/cmake/DNACalib/DNACalibTargets-*.cmake")
      if(_cmake_old_config_files)
        string(REPLACE ";" ", " _cmake_old_config_files_text "${_cmake_old_config_files}")
        message(STATUS "Old export file \"$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/cmake/DNACalib/DNACalibTargets.cmake\" will be replaced.  Removing files [${_cmake_old_config_files_text}].")
        unset(_cmake_old_config_files_text)
        file(REMOVE ${_cmake_old_config_files})
      endif()
      unset(_cmake_old_config_files)
    endif()
    unset(_cmake_export_file_changed)
  endif()
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib/cmake/DNACalib" TYPE FILE FILES "C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/build/DNACalib/CMakeFiles/Export/5c635dbe6b9c68e293e1ec21692732fa/DNACalibTargets.cmake")
  if(CMAKE_INSTALL_CONFIG_NAME MATCHES "^([Dd][Ee][Bb][Uu][Gg])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib/cmake/DNACalib" TYPE FILE FILES "C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/build/DNACalib/CMakeFiles/Export/5c635dbe6b9c68e293e1ec21692732fa/DNACalibTargets-debug.cmake")
  endif()
  if(CMAKE_INSTALL_CONFIG_NAME MATCHES "^([Mm][Ii][Nn][Ss][Ii][Zz][Ee][Rr][Ee][Ll])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib/cmake/DNACalib" TYPE FILE FILES "C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/build/DNACalib/CMakeFiles/Export/5c635dbe6b9c68e293e1ec21692732fa/DNACalibTargets-minsizerel.cmake")
  endif()
  if(CMAKE_INSTALL_CONFIG_NAME MATCHES "^([Rr][Ee][Ll][Ww][Ii][Tt][Hh][Dd][Ee][Bb][Ii][Nn][Ff][Oo])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib/cmake/DNACalib" TYPE FILE FILES "C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/build/DNACalib/CMakeFiles/Export/5c635dbe6b9c68e293e1ec21692732fa/DNACalibTargets-relwithdebinfo.cmake")
  endif()
  if(CMAKE_INSTALL_CONFIG_NAME MATCHES "^([Rr][Ee][Ll][Ee][Aa][Ss][Ee])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib/cmake/DNACalib" TYPE FILE FILES "C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/build/DNACalib/CMakeFiles/Export/5c635dbe6b9c68e293e1ec21692732fa/DNACalibTargets-release.cmake")
  endif()
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "dnacalib" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib/cmake/DNACalib" TYPE FILE RENAME "DNACalibConfig.cmake" FILES "C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/build/DNACalib/DNACalibConfig.install.cmake")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "dnacalib" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib/cmake/DNACalib" TYPE FILE FILES "C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/build/DNACalib/DNACalibConfigVersion.cmake")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "dnacalib" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/include" TYPE DIRECTORY FILES "C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/DNACalib/include/")
endif()

if(NOT CMAKE_INSTALL_LOCAL_ONLY)
  # Include the install script for each subdirectory.
  include("C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/build/DNACalib/examples/cmake_install.cmake")

endif()

string(REPLACE ";" "\n" CMAKE_INSTALL_MANIFEST_CONTENT
       "${CMAKE_INSTALL_MANIFEST_FILES}")
if(CMAKE_INSTALL_LOCAL_ONLY)
  file(WRITE "C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/build/DNACalib/install_local_manifest.txt"
     "${CMAKE_INSTALL_MANIFEST_CONTENT}")
endif()
