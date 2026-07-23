#ifndef CINTEL_FIXTURE_SENSOR_H
#define CINTEL_FIXTURE_SENSOR_H

#include "cintel_fixture/message.h"

int sensor_initialize(void);
int sensor_poll(Message *message);
unsigned int sensor_poll_count(void);

#endif
