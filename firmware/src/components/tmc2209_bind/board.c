#include "board.h"

#include "sdkconfig.h"

/*
 * The machine as this image sees it. Growing the machine is growing this table,
 * from menuconfig.
 *
 * The name is what the PC shows. Name it after what it moves: "capstan"
 * survives a rewiring, "drv0" does not.
 */

#if !defined(CONFIG_STEF_DRV0_ENABLED) && !defined(CONFIG_STEF_DRV1_ENABLED) && \
    !defined(CONFIG_STEF_DRV2_ENABLED)
#error "No driver is fitted. Enable at least one under STEF Board in menuconfig."
#endif

/* clang-format off */
static const board_driver_t drivers[] = {
#ifdef CONFIG_STEF_DRV0_ENABLED
    {
        .name = CONFIG_STEF_DRV0_NAME,
        .addr = CONFIG_STEF_DRV0_ADDR,
        .enn  = CONFIG_STEF_DRV0_ENN_GPIO,
        .dir  = CONFIG_STEF_DRV0_DIR_GPIO,
        .step = CONFIG_STEF_DRV0_STEP_GPIO,
        .diag = CONFIG_STEF_DRV0_DIAG_GPIO,
    },
#endif
#ifdef CONFIG_STEF_DRV1_ENABLED
    {
        .name = CONFIG_STEF_DRV1_NAME,
        .addr = CONFIG_STEF_DRV1_ADDR,
        .enn  = CONFIG_STEF_DRV1_ENN_GPIO,
        .dir  = CONFIG_STEF_DRV1_DIR_GPIO,
        .step = CONFIG_STEF_DRV1_STEP_GPIO,
        .diag = CONFIG_STEF_DRV1_DIAG_GPIO,
    },
#endif
#ifdef CONFIG_STEF_DRV2_ENABLED
    {
        .name = CONFIG_STEF_DRV2_NAME,
        .addr = CONFIG_STEF_DRV2_ADDR,
        .enn  = CONFIG_STEF_DRV2_ENN_GPIO,
        .dir  = CONFIG_STEF_DRV2_DIR_GPIO,
        .step = CONFIG_STEF_DRV2_STEP_GPIO,
        .diag = CONFIG_STEF_DRV2_DIAG_GPIO,
    },
#endif
};
/* clang-format on */

static const board_t board = {
    .uart_num = CONFIG_STEF_TMC_UART_NUM,
    .uart_tx  = CONFIG_STEF_TMC_UART_TX_GPIO,
    .uart_rx  = CONFIG_STEF_TMC_UART_RX_GPIO,
    .baud     = CONFIG_STEF_TMC_BAUD,

    /*
     * A TMC2209 answers a read in well under a millisecond, so this is how long
     * the bus waits for a driver that is not there. Short enough that probing an
     * empty address is quick, long enough to survive a scheduler hiccup.
     */
    .timeout_ms = 20,
    .retries    = 2,

    .drivers   = drivers,
    .n_drivers = sizeof(drivers) / sizeof(drivers[0]),
};

const board_t *board_get(void)
{
    return &board;
}
