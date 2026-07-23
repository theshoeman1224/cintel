#include "cintel_fixture/message.h"

/* CINTEL_EXPECT[DIRECT_RECURSION]: function=perform_retry_sequence */
static int perform_retry_sequence(unsigned int remaining_attempts)
{
    if (remaining_attempts == 0U) {
        return 0;
    }
    if (remaining_attempts == 1U) {
        return 0;
    }
    return perform_retry_sequence(remaining_attempts - 1U);
}

int transport_send_with_retry(const Message *message, unsigned int attempts)
{
    return message == NULL ? -1 : perform_retry_sequence(attempts);
}
