#ifndef CINTEL_FIXTURE_CYCLE_A_H
#define CINTEL_FIXTURE_CYCLE_A_H

struct CycleB;

typedef struct CycleA {
    int value;
    struct CycleB *peer;
} CycleA;

/* CINTEL_EXPECT[INCLUDE_CYCLE]: from=cycle_a.h; to=cycle_b.h */
#include "cintel_fixture/cycle_b.h"

#endif
