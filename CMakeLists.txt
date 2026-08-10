cmake_minimum_required(VERSION 3.21)

project(MultiplayerEdit VERSION 0.5.1)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Apple-only architecture selection. Do not leak macOS/iOS settings into
# Android cross-compilation.
if (APPLE)
    if ("${CMAKE_SYSTEM_NAME}" STREQUAL "iOS" OR IOS)
        set(CMAKE_OSX_ARCHITECTURES "arm64")
    else()
        set(CMAKE_OSX_ARCHITECTURES "arm64;x86_64")
    endif()
endif()

# Windows-only definitions to prevent Win32 macros from breaking C++
# std::min/std::max/limits. These must not be exported to Android builds.
if (WIN32)
    add_compile_definitions(WIN32_LEAN_AND_MEAN)
    add_compile_definitions(NOMINMAX)
    add_compile_definitions(_WINSOCKAPI_)
endif()

file(GLOB_RECURSE SOURCES CONFIGURE_DEPENDS src/*.cpp)

add_library(${PROJECT_NAME} SHARED ${SOURCES})
target_include_directories(${PROJECT_NAME} PRIVATE src)

# ── Skip Install Rules ──────────────────────────────────────
# Disable install rules to prevent target export issues with built-from-source deps
set(CMAKE_SKIP_INSTALL_RULES ON)

include(FetchContent)

# ── MbedTLS 3.x ─────────────────────────────────────────────
FetchContent_Declare(
    mbedtls
    GIT_REPOSITORY https://github.com/Mbed-TLS/mbedtls.git
    GIT_TAG        v3.6.0
)
set(ENABLE_TESTING OFF CACHE BOOL "" FORCE)
set(ENABLE_PROGRAMS OFF CACHE BOOL "" FORCE)
set(MBEDTLS_FATAL_WARNINGS OFF CACHE BOOL "" FORCE)

FetchContent_GetProperties(mbedtls)
if(NOT mbedtls_POPULATED)
    FetchContent_Populate(mbedtls)
    
    # Patch MbedTLS configuration to enable MBEDTLS_SSL_DTLS_SRTP (required by WebRTC/libdatachannel)
    set(MBEDTLS_CONFIG_H "${mbedtls_SOURCE_DIR}/include/mbedtls/mbedtls_config.h")
    if(EXISTS "${MBEDTLS_CONFIG_H}")
        message(STATUS "Patching ${MBEDTLS_CONFIG_H} to enable MBEDTLS_SSL_DTLS_SRTP...")
        file(READ "${MBEDTLS_CONFIG_H}" MBEDTLS_CONFIG_CONTENTS)
        string(REPLACE "//#define MBEDTLS_SSL_DTLS_SRTP" 
                       "#define MBEDTLS_SSL_DTLS_SRTP" 
                       MBEDTLS_CONFIG_CONTENTS "${MBEDTLS_CONFIG_CONTENTS}")
        file(WRITE "${MBEDTLS_CONFIG_H}" "${MBEDTLS_CONFIG_CONTENTS}")
    endif()
    
    add_subdirectory(${mbedtls_SOURCE_DIR} ${mbedtls_BINARY_DIR})
endif()

# Create the alias target that libdatachannel expects to find
if (TARGET mbedtls AND NOT TARGET MbedTLS::MbedTLS)
    add_library(MbedTLS::MbedTLS ALIAS mbedtls)
endif()

# ── libdatachannel (WebRTC Data Channels) ──────────────────
FetchContent_Declare(
    libdatachannel
    GIT_REPOSITORY https://github.com/paullouisageneau/libdatachannel.git
    GIT_TAG        v0.22.4
)

# Configure libdatachannel settings
set(NO_MEDIA ON CACHE BOOL "" FORCE)
set(NO_WEBSOCKET ON CACHE BOOL "" FORCE)
set(NO_EXAMPLES ON CACHE BOOL "" FORCE)
set(NO_TESTS ON CACHE BOOL "" FORCE)

set(USE_GNUTLS OFF CACHE BOOL "" FORCE)
set(USE_NICE OFF CACHE BOOL "" FORCE)
set(PREFER_SYSTEM_LIB OFF CACHE BOOL "" FORCE)

set(USE_OPENSSL OFF CACHE BOOL "" FORCE)
set(USE_MBEDTLS ON CACHE BOOL "" FORCE)

# Populate and patch libdatachannel before making it available
FetchContent_GetProperties(libdatachannel)
if(NOT libdatachannel_POPULATED)
    FetchContent_Populate(libdatachannel)
    
    # Patch usrsctp warning flags for Clang cross-compilation
    set(USRSCTP_CMAKE "${libdatachannel_SOURCE_DIR}/deps/usrsctp/CMakeLists.txt")
    if(EXISTS "${USRSCTP_CMAKE}")
        message(STATUS "Patching ${USRSCTP_CMAKE} for Clang compiler warning flags...")
        file(READ "${USRSCTP_CMAKE}" USRSCTP_CONTENTS)
        string(REPLACE "if (CMAKE_C_COMPILER_ID MATCHES \"MSVC\" OR CMAKE_C_SIMULATE_ID MATCHES \"MSVC\")" 
                       "if ((CMAKE_C_COMPILER_ID MATCHES \"MSVC\" OR CMAKE_C_SIMULATE_ID MATCHES \"MSVC\") AND NOT CMAKE_C_COMPILER_ID MATCHES \"Clang\")" 
                       USRSCTP_CONTENTS "${USRSCTP_CONTENTS}")
        file(WRITE "${USRSCTP_CMAKE}" "${USRSCTP_CONTENTS}")
    endif()
    
    add_subdirectory(${libdatachannel_SOURCE_DIR} ${libdatachannel_BINARY_DIR})
endif()

target_link_libraries(${PROJECT_NAME} LibDataChannel::LibDataChannelStatic)

# ── Geode SDK ──────────────────────────────────────────────
if (NOT DEFINED ENV{GEODE_SDK})
    message(FATAL_ERROR "Unable to find Geode SDK! Please define GEODE_SDK environment variable to point to Geode")
else()
    message(STATUS "Found Geode: $ENV{GEODE_SDK}")
endif()

# Re-enable install rules specifically for the Geode SDK and the mod target
set(CMAKE_SKIP_INSTALL_RULES OFF)

add_subdirectory($ENV{GEODE_SDK} ${CMAKE_CURRENT_BINARY_DIR}/geode)

if (WIN32)
    target_link_options(${PROJECT_NAME} PRIVATE "-Wl,/MAP")
endif()

setup_geode_mod(${PROJECT_NAME})
