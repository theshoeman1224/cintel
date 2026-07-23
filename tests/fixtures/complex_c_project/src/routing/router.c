#include "cintel_fixture/router.h"

#define MAX_HANDLERS 8U

/* CINTEL_EXPECT[TYPE_DEFINITION]: symbol=g_default_handler; kind=global_structure */
MessageHandler g_default_handler = {MESSAGE_TYPE_DIAGNOSTIC, NULL, NULL};
static MessageHandler s_handlers[MAX_HANDLERS];
static size_t s_handler_count;
static unsigned int s_dispatch_count;
static const int s_priority_table[] = {0, 10, 20, 30};

/* CINTEL_EXPECT[DUPLICATE_STATIC_NAME]: symbol=normalize_value; distinct_by=file */
static int normalize_value(int value)
{
    return fixture_clamp(value, -1000, 1000);
}

int router_initialize(void)
{
    s_handler_count = 0U;
    s_dispatch_count = 0U;
    return normalize_value(s_priority_table[0]);
}

int router_register_handler(const MessageHandler *handler)
{
    if (handler == NULL || handler->handler == NULL || s_handler_count >= MAX_HANDLERS) {
        return -1;
    }
    s_handlers[s_handler_count++] = *handler;
    return 0;
}

/* CINTEL_EXPECT[HIGH_COMPLEXITY]: function=router_classify_message */
RouteResult router_classify_message(const Message *message)
{
    if (message == NULL) {
        return ROUTE_RESULT_INVALID;
    }
    if (message->payload_size > 1024U) {
        return ROUTE_RESULT_DROPPED;
    }
    switch (message->type) {
    case MESSAGE_TYPE_SENSOR:
        if (!message->reading.flags.valid) {
            return ROUTE_RESULT_INVALID;
        }
        if (message->reading.value.signed_value < 0) {
            return USE_FAST_FILTER ? ROUTE_RESULT_DROPPED : ROUTE_RESULT_RETRY;
        }
        return message->identifier == 0U ? ROUTE_RESULT_DROPPED : ROUTE_RESULT_HANDLED;
    case MESSAGE_TYPE_CONTROL:
        return message->payload == NULL ? ROUTE_RESULT_RETRY : ROUTE_RESULT_HANDLED;
    case MESSAGE_TYPE_DIAGNOSTIC:
        return ROUTE_RESULT_HANDLED;
    default:
        return ROUTE_RESULT_INVALID;
    }
}

RouteResult router_dispatch(const Message *message)
{
    size_t index;
    RouteResult classification = router_classify_message(message);

    ++s_dispatch_count;
    if (classification != ROUTE_RESULT_HANDLED) {
        return classification;
    }
    for (index = 0U; index < s_handler_count; ++index) {
        if (s_handlers[index].accepted_type == message->type) {
            /* CINTEL_EXPECT[POSSIBLE_INDIRECT_CALL]: caller=router_dispatch; callback_field=handler */
            return s_handlers[index].handler(message, s_handlers[index].context);
        }
    }
    return ROUTE_RESULT_DROPPED;
}

unsigned int router_dispatch_count(void)
{
    return s_dispatch_count;
}
