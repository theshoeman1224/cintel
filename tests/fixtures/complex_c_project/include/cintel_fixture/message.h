#ifndef CINTEL_FIXTURE_MESSAGE_H
#define CINTEL_FIXTURE_MESSAGE_H

#include "cintel_fixture/types.h"

typedef struct Message {
    MessageType type;
    unsigned int identifier;
    SensorReading reading;
    const void *payload;
    size_t payload_size;
} Message;

#endif
