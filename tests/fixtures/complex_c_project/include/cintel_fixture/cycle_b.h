#ifndef CINTEL_FIXTURE_CYCLE_B_H
#define CINTEL_FIXTURE_CYCLE_B_H

struct CycleA;

typedef struct CycleB {
    int value;
    struct CycleA *peer;
} CycleB;

/* CINTEL_EXPECT[INCLUDE_CYCLE]: from=cycle_b.h; to=cycle_a.h */
#include "cintel_fixture/cycle_a.h"

#endif
