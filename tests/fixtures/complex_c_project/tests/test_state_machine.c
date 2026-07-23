#include <stdio.h>

#include "cintel_fixture/state_machine.h"

#define FIXTURE_ASSERT(condition)                                                         \
    do {                                                                                  \
        if (!(condition)) {                                                               \
            fprintf(stderr, "assertion failed: %s:%d: %s\n", __FILE__, __LINE__, #condition); \
            ++failures;                                                                   \
        }                                                                                 \
    } while (0)

int test_state_machine(void)
{
    int failures = 0;
    Message message = {0};

    state_machine_reset();
    message.type = MESSAGE_TYPE_SENSOR;
    FIXTURE_ASSERT(state_machine_process(&message, ROUTE_RESULT_HANDLED) == MACHINE_STATE_ACTIVE);
    FIXTURE_ASSERT(state_machine_process(NULL, ROUTE_RESULT_INVALID) == MACHINE_STATE_FAULT);
    return failures;
}
