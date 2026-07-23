#include "cintel_fixture/types.h"

int conversion_apply_limits(int value, const RuntimeLimits *limits)
{
    return limits == NULL ? value : fixture_clamp(value, limits->minimum, limits->maximum);
}
