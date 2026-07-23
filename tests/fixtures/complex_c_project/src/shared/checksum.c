#include <stddef.h>
#include <stdint.h>

/* CINTEL_EXPECT[MULTI_CONFIGURATION_UNIT]: path=src/shared/checksum.c; configurations=linux,embedded,tests */
uint32_t checksum_compute(const unsigned char *data, size_t size)
{
    uint32_t checksum = 0U;
    size_t index;

    for (index = 0U; index < size; ++index) {
        checksum = (checksum * 33U) ^ data[index];
    }
#if CHECKSUM_WIDTH == 16
    checksum &= 0xFFFFU;
#endif
    return checksum;
}
