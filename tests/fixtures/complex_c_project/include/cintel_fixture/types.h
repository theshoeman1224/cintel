#ifndef CINTEL_FIXTURE_TYPES_H
#define CINTEL_FIXTURE_TYPES_H

#include <stddef.h>
#include <stdint.h>

/* CINTEL_EXPECT[TYPE_DEFINITION]: symbol=AppStatus; kind=enum */
typedef enum AppStatus {
    APP_STATUS_OK = 0,
    APP_STATUS_INITIALIZATION_FAILED = 1,
    APP_STATUS_RUNTIME_ERROR = 2
} AppStatus;

typedef enum MessageType {
    MESSAGE_TYPE_SENSOR = 1,
    MESSAGE_TYPE_CONTROL = 2,
    MESSAGE_TYPE_DIAGNOSTIC = 3
} MessageType;

typedef enum RouteResult {
    ROUTE_RESULT_HANDLED = 0,
    ROUTE_RESULT_DROPPED = 1,
    ROUTE_RESULT_INVALID = 2,
    ROUTE_RESULT_RETRY = 3
} RouteResult;

typedef union SensorValue {
    int32_t signed_value;
    uint32_t unsigned_value;
    float floating_value;
} SensorValue;

typedef struct SensorFlags {
    unsigned int valid : 1;
    unsigned int calibrated : 1;
    unsigned int reserved : 6;
} SensorFlags;

typedef struct SensorReading {
    unsigned int sensor_id;
    SensorValue value;
    SensorFlags flags;
} SensorReading;

typedef struct RuntimeLimits {
    int minimum;
    int maximum;
} RuntimeLimits;

typedef struct FixtureConfiguration {
    RuntimeLimits limits;
    unsigned int retry_count;
    int telemetry_enabled;
} FixtureConfiguration;

static inline int fixture_clamp(int value, int minimum, int maximum)
{
    return value < minimum ? minimum : (value > maximum ? maximum : value);
}

#endif
