#include "cintel_fixture/telemetry.h"

static unsigned int s_publish_count;

int telemetry_initialize(void)
{
    s_publish_count = 0U;
    return 0;
}

void telemetry_publish(const Message *message)
{
    if (message != NULL) {
        ++s_publish_count;
    }
}

unsigned int telemetry_publish_count(void)
{
    return s_publish_count;
}
