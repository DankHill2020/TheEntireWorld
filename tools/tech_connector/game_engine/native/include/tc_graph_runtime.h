#ifndef TC_GRAPH_RUNTIME_H
#define TC_GRAPH_RUNTIME_H

#include <stdint.h>

#if defined(_WIN32)
#  if defined(TC_GRAPH_RUNTIME_BUILD)
#    define TC_GRAPH_API __declspec(dllexport)
#  else
#    define TC_GRAPH_API __declspec(dllimport)
#  endif
#else
#  define TC_GRAPH_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

#define TC_GRAPH_ABI_VERSION 1u

typedef enum TcGraphStatus {
    TC_GRAPH_STATUS_OK = 0,
    TC_GRAPH_STATUS_NULL_POINTER = 1,
    TC_GRAPH_STATUS_NON_FINITE_VALUE = 2,
    TC_GRAPH_STATUS_OUT_OF_RANGE = 3
} TcGraphStatus;

typedef struct TcGraphVector2 {
    float x;
    float y;
} TcGraphVector2;

typedef struct TcGraphVector3 {
    float x;
    float y;
    float z;
} TcGraphVector3;

typedef struct TcGraphMovementInput {
    TcGraphVector2 direction;
    TcGraphVector3 current_velocity;
    float maximum_speed;
    float acceleration;
    float delta_seconds;
} TcGraphMovementInput;

TC_GRAPH_API uint32_t tc_graph_abi_version(void);
TC_GRAPH_API const char* tc_graph_status_message(TcGraphStatus status);

TC_GRAPH_API TcGraphStatus tc_graph_clamp_input_axis(
    const TcGraphVector2* input,
    TcGraphVector2* output
);

TC_GRAPH_API TcGraphStatus tc_graph_calculate_movement_velocity(
    const TcGraphMovementInput* input,
    TcGraphVector3* output
);

#ifdef __cplusplus
}
#endif

#endif
