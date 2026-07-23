#include <stdio.h>

#include "cintel_fixture/router.h"

#define FIXTURE_ASSERT(condition)                                                         \
    do {                                                                                  \
        if (!(condition)) {                                                               \
            fprintf(stderr, "assertion failed: %s:%d: %s\n", __FILE__, __LINE__, #condition); \
            ++failures;                                                                   \
        }                                                                                 \
    } while (0)

int test_router(void)
{
    int failures = 0;
    Message message = {0};

    message.type = MESSAGE_TYPE_SENSOR;
    message.identifier = 1U;
    message.reading.flags.valid = 1U;
    message.reading.value.signed_value = 10;
    FIXTURE_ASSERT(router_classify_message(&message) == ROUTE_RESULT_HANDLED);
    message.reading.flags.valid = 0U;
    FIXTURE_ASSERT(router_classify_message(&message) == ROUTE_RESULT_INVALID);
    FIXTURE_ASSERT(router_classify_message(NULL) == ROUTE_RESULT_INVALID);
    return failures;
}
