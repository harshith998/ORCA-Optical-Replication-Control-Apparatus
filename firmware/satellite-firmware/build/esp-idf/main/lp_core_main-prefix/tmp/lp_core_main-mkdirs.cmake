# Distributed under the OSI-approved BSD 3-Clause License.  See accompanying
# file LICENSE.rst or https://cmake.org/licensing for details.

cmake_minimum_required(VERSION ${CMAKE_VERSION}) # this file comes with cmake

# If CMAKE_DISABLE_SOURCE_CHANGES is set to true and the source directory is an
# existing directory in our source tree, calling file(MAKE_DIRECTORY) on it
# would cause a fatal error, even though it would be a no-op.
if(NOT EXISTS "/Users/michaeldanley/espressif/v5.5/esp-idf/components/ulp/cmake")
  file(MAKE_DIRECTORY "/Users/michaeldanley/espressif/v5.5/esp-idf/components/ulp/cmake")
endif()
file(MAKE_DIRECTORY
  "/Users/michaeldanley/Documents/GitHub/ORCA-Optical-Replication-Control-Apparatus/firmware/satellite-firmware/build/esp-idf/main/lp_core_main"
  "/Users/michaeldanley/Documents/GitHub/ORCA-Optical-Replication-Control-Apparatus/firmware/satellite-firmware/build/esp-idf/main/lp_core_main-prefix"
  "/Users/michaeldanley/Documents/GitHub/ORCA-Optical-Replication-Control-Apparatus/firmware/satellite-firmware/build/esp-idf/main/lp_core_main-prefix/tmp"
  "/Users/michaeldanley/Documents/GitHub/ORCA-Optical-Replication-Control-Apparatus/firmware/satellite-firmware/build/esp-idf/main/lp_core_main-prefix/src/lp_core_main-stamp"
  "/Users/michaeldanley/Documents/GitHub/ORCA-Optical-Replication-Control-Apparatus/firmware/satellite-firmware/build/esp-idf/main/lp_core_main-prefix/src"
  "/Users/michaeldanley/Documents/GitHub/ORCA-Optical-Replication-Control-Apparatus/firmware/satellite-firmware/build/esp-idf/main/lp_core_main-prefix/src/lp_core_main-stamp"
)

set(configSubDirs )
foreach(subDir IN LISTS configSubDirs)
    file(MAKE_DIRECTORY "/Users/michaeldanley/Documents/GitHub/ORCA-Optical-Replication-Control-Apparatus/firmware/satellite-firmware/build/esp-idf/main/lp_core_main-prefix/src/lp_core_main-stamp/${subDir}")
endforeach()
if(cfgdir)
  file(MAKE_DIRECTORY "/Users/michaeldanley/Documents/GitHub/ORCA-Optical-Replication-Control-Apparatus/firmware/satellite-firmware/build/esp-idf/main/lp_core_main-prefix/src/lp_core_main-stamp${cfgdir}") # cfgdir has leading slash
endif()
