# Code shared by all node firmware. Link with: target_link_libraries(<target> mosaic_common)
add_library(mosaic_common INTERFACE)
target_include_directories(mosaic_common INTERFACE ${CMAKE_CURRENT_LIST_DIR}/include)

# Compile the protocol header for the RP2040 so its layout static asserts run
# with the real ARM compiler on every build. Not linked or flashed.
add_library(mosaic_protocol_layout_check OBJECT test/protocol_dump.c)
target_link_libraries(mosaic_protocol_layout_check PRIVATE mosaic_common)
