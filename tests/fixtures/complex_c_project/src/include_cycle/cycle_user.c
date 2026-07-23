#include <stddef.h>

#include "cintel_fixture/cycle_a.h"

int cycle_sum(const CycleA *a, const CycleB *b)
{
    return (a == NULL ? 0 : a->value) + (b == NULL ? 0 : b->value);
}
