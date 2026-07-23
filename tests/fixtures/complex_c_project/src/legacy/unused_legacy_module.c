/* CINTEL_EXPECT[BUILD_EXCLUDED_FILE]: path=src/legacy/unused_legacy_module.c; builds=all */
static int legacy_adjust(int value)
{
    return value + 1970;
}

int unused_legacy_entry(int value)
{
    return legacy_adjust(value);
}
