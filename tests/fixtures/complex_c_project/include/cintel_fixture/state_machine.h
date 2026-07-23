#ifndef CINTEL_FIXTURE_STATE_MACHINE_H
#define CINTEL_FIXTURE_STATE_MACHINE_H

#include "cintel_fixture/message.h"

typedef enum MachineState {
    MACHINE_STATE_IDLE = 0,
    MACHINE_STATE_ACTIVE = 1,
    MACHINE_STATE_FAULT = 2
} MachineState;

void state_machine_reset(void);
MachineState state_machine_process(const Message *message, RouteResult route_result);
MachineState state_machine_current(void);

#endif
