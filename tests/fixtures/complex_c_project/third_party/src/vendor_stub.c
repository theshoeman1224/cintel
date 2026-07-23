#include "vendor/vendor_api.h"

int vendor_transform(int value)
{
    return value ^ 0x5A;
}
