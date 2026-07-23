#include "cintel_fixture/state_machine.h"

static MachineState s_state = MACHINE_STATE_IDLE;

void state_machine_reset(void)
{
    s_state = MACHINE_STATE_IDLE;
}

MachineState state_machine_process(const Message *message, RouteResult route_result)
{
    if (message == NULL || route_result == ROUTE_RESULT_INVALID) {
        s_state = MACHINE_STATE_FAULT;
    } else if (route_result == ROUTE_RESULT_HANDLED) {
        s_state = MACHINE_STATE_ACTIVE;
    } else if (message->type == MESSAGE_TYPE_CONTROL) {
        s_state = MACHINE_STATE_IDLE;
    }
    return s_state;
}

MachineState state_machine_current(void)
{
    return s_state;
}
