#ifndef CINTEL_FIXTURE_TELEMETRY_H
#define CINTEL_FIXTURE_TELEMETRY_H

#include "cintel_fixture/message.h"

int telemetry_initialize(void);
void telemetry_publish(const Message *message);
unsigned int telemetry_publish_count(void);

#endif
