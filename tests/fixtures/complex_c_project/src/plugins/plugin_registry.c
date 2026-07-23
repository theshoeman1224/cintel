#include "cintel_fixture/plugin.h"

static const PluginDescriptor s_plugins[] = {
    {1U, "alpha", plugin_alpha_handle},
    {2U, "beta", plugin_beta_handle},
};

const PluginDescriptor *plugin_registry(size_t *count)
{
    if (count != NULL) {
        *count = sizeof(s_plugins) / sizeof(s_plugins[0]);
    }
    return s_plugins;
}

int plugin_register_all(void)
{
    size_t index;
    size_t count;
    const PluginDescriptor *plugins = plugin_registry(&count);

    for (index = 0U; index < count; ++index) {
        MessageHandler handler = {MESSAGE_TYPE_SENSOR, plugins[index].handler, NULL};
        if (router_register_handler(&handler) != 0) {
            return -1;
        }
    }
    return 0;
}
