#include "cintel_fixture/sensor.h"
#include "vendor/vendor_api.h"

uint32_t checksum_compute(const unsigned char *data, size_t size);
int transport_send_with_retry(const Message *message, unsigned int attempts);

static unsigned int s_poll_count = 0U;

int sensor_initialize(void)
{
    s_poll_count = 0U;
    return 0;
}

int sensor_poll(Message *message)
{
    static const unsigned char sample_data[] = {1U, 2U, 3U, 4U};

    if (message == NULL) {
        return -1;
    }
    ++s_poll_count;
    message->type = MESSAGE_TYPE_SENSOR;
    message->identifier = (s_poll_count % 2U) + 1U;
    message->reading.sensor_id = message->identifier;
    message->reading.value.signed_value = vendor_transform((int)checksum_compute(
        sample_data, sizeof(sample_data)));
    message->reading.flags.valid = 1U;
    message->reading.flags.calibrated = USE_FAST_FILTER ? 1U : 0U;
    message->payload = NULL;
    message->payload_size = 0U;
    return transport_send_with_retry(message, 2U);
}

unsigned int sensor_poll_count(void)
{
    return s_poll_count;
}
