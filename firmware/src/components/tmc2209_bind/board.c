#include "board.h"

#include "sdkconfig.h"

/*
 * One entry today, because the bench board is one driver socketed onto one
 * ESP32. The carrier board is three entries in this array and nothing else:
 * every layer above addresses a driver by the name written here, so growing
 * the machine is growing the table.
 *
 * The name is what the PC says. Keep it mechanical rather than electrical:
 * "capstan" survives a rewiring, "drv0" does not.
 */
static const board_driver_t drivers[] = {
    {
        .name = CONFIG_STEF_DRV0_NAME,
        .addr = CONFIG_STEF_DRV0_ADDR,
        .enn  = CONFIG_STEF_DRV0_ENN_GPIO,
        .dir  = CONFIG_STEF_DRV0_DIR_GPIO,
        .step = CONFIG_STEF_DRV0_STEP_GPIO,
        .diag = CONFIG_STEF_DRV0_DIAG_GPIO,
    },
};

static const board_t board = {
    .uart_num = CONFIG_STEF_TMC_UART_NUM,
    .uart_tx  = CONFIG_STEF_TMC_UART_TX_GPIO,
    .uart_rx  = CONFIG_STEF_TMC_UART_RX_GPIO,
    .baud     = CONFIG_STEF_TMC_BAUD,

    /*
     * A TMC2209 answers a read in well under a millisecond, so the timeout is
     * not waiting for the part: it is how long the bus tolerates a driver that
     * is not there before saying so. Short enough that probing an empty
     * address is quick, long enough to survive a scheduler hiccup.
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
