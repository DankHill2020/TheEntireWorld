# Install script for directory: C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/PyDNA/python3

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

if(CMAKE_INSTALL_COMPONENT STREQUAL "PyDNA-py3.9" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/py3.9" TYPE FILE FILES "C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/build/py3.9/dna.py")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "PyDNA-py3.9" OR NOT CMAKE_INSTALL_COMPONENT)
  if(CMAKE_INSTALL_CONFIG_NAME MATCHES "^([Dd][Ee][Bb][Uu][Gg])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/py3.9" TYPE STATIC_LIBRARY OPTIONAL FILES "C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/build/PyDNA/python3/Debug/py3dna.lib")
  elseif(CMAKE_INSTALL_CONFIG_NAME MATCHES "^([Rr][Ee][Ll][Ee][Aa][Ss][Ee])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/py3.9" TYPE STATIC_LIBRARY OPTIONAL FILES "C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/build/PyDNA/python3/Release/py3dna.lib")
  elseif(CMAKE_INSTALL_CONFIG_NAME MATCHES "^([Mm][Ii][Nn][Ss][Ii][Zz][Ee][Rr][Ee][Ll])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/py3.9" TYPE STATIC_LIBRARY OPTIONAL FILES "C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/build/PyDNA/python3/MinSizeRel/py3dna.lib")
  elseif(CMAKE_INSTALL_CONFIG_NAME MATCHES "^([Rr][Ee][Ll][Ww][Ii][Tt][Hh][Dd][Ee][Bb][Ii][Nn][Ff][Oo])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/py3.9" TYPE STATIC_LIBRARY OPTIONAL FILES "C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/build/PyDNA/python3/RelWithDebInfo/py3dna.lib")
  endif()
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "PyDNA-py3.9" OR NOT CMAKE_INSTALL_COMPONENT)
  if(CMAKE_INSTALL_CONFIG_NAME MATCHES "^([Dd][Ee][Bb][Uu][Gg])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/py3.9" TYPE SHARED_LIBRARY FILES "C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/build/PyDNA/python3/Debug/_py3dna.pyd")
  elseif(CMAKE_INSTALL_CONFIG_NAME MATCHES "^([Rr][Ee][Ll][Ee][Aa][Ss][Ee])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/py3.9" TYPE SHARED_LIBRARY FILES "C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/build/PyDNA/python3/Release/_py3dna.pyd")
  elseif(CMAKE_INSTALL_CONFIG_NAME MATCHES "^([Mm][Ii][Nn][Ss][Ii][Zz][Ee][Rr][Ee][Ll])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/py3.9" TYPE SHARED_LIBRARY FILES "C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/build/PyDNA/python3/MinSizeRel/_py3dna.pyd")
  elseif(CMAKE_INSTALL_CONFIG_NAME MATCHES "^([Rr][Ee][Ll][Ww][Ii][Tt][Hh][Dd][Ee][Bb][Ii][Nn][Ff][Oo])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/py3.9" TYPE SHARED_LIBRARY FILES "C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/build/PyDNA/python3/RelWithDebInfo/_py3dna.pyd")
  endif()
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "PyDNA-py3.9" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/py3.9" TYPE FILE RENAME "dna_demo.py" FILES "C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/PyDNA/python3/examples/demo.py")
endif()

string(REPLACE ";" "\n" CMAKE_INSTALL_MANIFEST_CONTENT
       "${CMAKE_INSTALL_MANIFEST_FILES}")
if(CMAKE_INSTALL_LOCAL_ONLY)
  file(WRITE "C:/depot/tools/external_tools/MetaHumanDNA/dnacalib/build/PyDNA/python3/install_local_manifest.txt"
     "${CMAKE_INSTALL_MANIFEST_CONTENT}")
endif()
