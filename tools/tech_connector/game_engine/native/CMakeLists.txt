cmake_minimum_required(VERSION 3.24)

project(tc_graph_runtime VERSION 0.1.0 LANGUAGES C CXX)

option(TC_GRAPH_BUILD_TESTS "Build native graph runtime tests" ON)
option(TC_RUNTIME_BUILD_PLAYER "Build the standalone TC player" ON)

add_library(tc_gpu_compute SHARED src/tc_gpu_compute.cpp)
target_compile_features(tc_gpu_compute PUBLIC cxx_std_23)
target_include_directories(tc_gpu_compute PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_compile_definitions(tc_gpu_compute PRIVATE TC_GPU_COMPUTE_BUILD=1 NOMINMAX)
if(WIN32)
    target_link_libraries(tc_gpu_compute PRIVATE d3d11 d3dcompiler)
endif()
if(MSVC)
    target_compile_options(tc_gpu_compute PRIVATE /W4 /WX /permissive- /EHsc)
else()
    target_compile_options(tc_gpu_compute PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

add_library(tc_graph_runtime SHARED
    src/tc_graph_runtime.cpp
)

target_compile_features(tc_graph_runtime PUBLIC cxx_std_23)
target_include_directories(tc_graph_runtime
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
)
target_compile_definitions(tc_graph_runtime PRIVATE TC_GRAPH_RUNTIME_BUILD=1)
set_target_properties(tc_graph_runtime PROPERTIES
    CXX_EXTENSIONS OFF
    OUTPUT_NAME "tc_graph_runtime"
    VERSION ${PROJECT_VERSION}
    SOVERSION 1
)

if(MSVC)
    target_compile_options(tc_graph_runtime PRIVATE /W4 /WX /permissive- /EHsc)
else()
    target_compile_options(tc_graph_runtime PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

add_library(tc_runtime_core STATIC src/tc_runtime_core.cpp src/tc_spatial_index.cpp src/tc_force_tree.cpp)
target_compile_features(tc_runtime_core PUBLIC cxx_std_23)
target_include_directories(tc_runtime_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_link_libraries(tc_runtime_core PUBLIC tc_graph_runtime)
if(MSVC)
    target_compile_options(tc_runtime_core PRIVATE /W4 /WX /permissive- /EHsc)
else()
    target_compile_options(tc_runtime_core PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

add_library(tc_audio_mixer STATIC src/tc_audio_mixer.cpp)
target_compile_features(tc_audio_mixer PUBLIC cxx_std_23)
target_include_directories(tc_audio_mixer PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
if(WIN32)
    target_compile_definitions(tc_audio_mixer PRIVATE NOMINMAX)
    target_link_libraries(tc_audio_mixer PRIVATE xaudio2)
endif()

add_library(tc_gpu_renderer STATIC src/tc_gpu_renderer.cpp)
target_compile_features(tc_gpu_renderer PUBLIC cxx_std_23)
target_include_directories(tc_gpu_renderer PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_link_libraries(tc_gpu_renderer PUBLIC tc_runtime_core)
if(WIN32)
    target_compile_definitions(tc_gpu_renderer PRIVATE NOMINMAX UNICODE _UNICODE)
    target_link_libraries(tc_gpu_renderer PRIVATE d3d11 dxgi d3dcompiler windowscodecs)
endif()
if(MSVC)
    target_compile_options(tc_gpu_renderer PRIVATE /W4 /WX /permissive- /EHsc)
else()
    target_compile_options(tc_gpu_renderer PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()
if(MSVC)
    target_compile_options(tc_audio_mixer PRIVATE /W4 /WX /permissive- /EHsc)
else()
    target_compile_options(tc_audio_mixer PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

if(TC_GRAPH_BUILD_TESTS)
    enable_testing()
    add_executable(tc_graph_runtime_tests tests/tc_graph_runtime_tests.cpp)
    target_compile_features(tc_graph_runtime_tests PRIVATE cxx_std_23)
    target_link_libraries(tc_graph_runtime_tests PRIVATE tc_graph_runtime)
    if(MSVC)
        target_compile_options(tc_graph_runtime_tests PRIVATE /W4 /WX /permissive- /EHsc)
    else()
        target_compile_options(tc_graph_runtime_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
    endif()
    add_test(NAME tc_graph_runtime_tests COMMAND tc_graph_runtime_tests)

    add_executable(tc_runtime_core_tests tests/tc_runtime_core_tests.cpp)
    target_compile_features(tc_runtime_core_tests PRIVATE cxx_std_23)
    target_link_libraries(tc_runtime_core_tests PRIVATE tc_runtime_core)
    if(MSVC)
        target_compile_options(tc_runtime_core_tests PRIVATE /W4 /WX /permissive- /EHsc)
    else()
        target_compile_options(tc_runtime_core_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
    endif()
    add_test(NAME tc_runtime_core_tests COMMAND tc_runtime_core_tests)

    add_executable(tc_gpu_renderer_tests tests/tc_gpu_renderer_tests.cpp)
    target_compile_features(tc_gpu_renderer_tests PRIVATE cxx_std_23)
    target_link_libraries(tc_gpu_renderer_tests PRIVATE tc_gpu_renderer)
    if(MSVC)
        target_compile_options(tc_gpu_renderer_tests PRIVATE /W4 /permissive- /EHsc)
    else()
        target_compile_options(tc_gpu_renderer_tests PRIVATE -Wall -Wextra -Wpedantic)
    endif()
    add_test(NAME tc_gpu_renderer_tests COMMAND tc_gpu_renderer_tests)
endif()

if(TC_RUNTIME_BUILD_PLAYER)
    add_executable(tc_player src/tc_player.cpp)
    target_compile_features(tc_player PRIVATE cxx_std_23)
    target_link_libraries(tc_player PRIVATE tc_runtime_core tc_audio_mixer tc_gpu_renderer)
    if(WIN32)
        target_compile_definitions(tc_player PRIVATE UNICODE _UNICODE NOMINMAX)
        target_link_libraries(tc_player PRIVATE user32 gdi32 winmm shell32)
        set_target_properties(tc_player PROPERTIES WIN32_EXECUTABLE TRUE)
    endif()
    if(MSVC)
        target_compile_options(tc_player PRIVATE /W4 /WX /permissive- /EHsc)
    else()
        target_compile_options(tc_player PRIVATE -Wall -Wextra -Wpedantic -Werror)
    endif()
endif()

include(GNUInstallDirs)
install(TARGETS tc_graph_runtime tc_gpu_compute
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
)
if(TC_RUNTIME_BUILD_PLAYER)
    install(TARGETS tc_player RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
endif()
install(FILES include/tc_graph_runtime.h include/tc_runtime_core.h include/tc_spatial_index.h include/tc_force_tree.h DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})
