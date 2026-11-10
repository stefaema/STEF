/* test_trip.c: the keepalive deadline and the trip, against a fake pulse source. */

#include <stdbool.h>
#include <string.h>

#include "fake_devices.h"
#include "fw_api.h"
#include "mock_tmc2209.h"
#include "rpc_dispatch.h"
#include "rpc_methods.h"
#include "rpc_trip.h"
#include "tmc2209.h"
#include "unity.h"

typedef struct {
    bool running;
    bool halted_immediately;
    int  halts;
} fake_gen_t;

static mock_dev_t        g_mock;
static tmc2209_uart_t    g_uart;
static tmc2209_t         g_dev;
static bool              g_level[TMC2209_LINE_COUNT];
static tmc2209_lines_t   g_lines;
static fake_gen_t        g_gen;
static tmc2209_stepgen_t g_stepgen;

static int board_read(void *ctx, tmc2209_line_t line)
{
    (void)ctx;
    return (int)g_level[line];
}

static int board_write(void *ctx, tmc2209_line_t line, bool level)
{
    (void)ctx;
    g_level[line] = level;
    return 0;
}

static int gen_run(void *ctx, const tmc2209_run_plan_t *plan)
{
    (void)plan;
    ((fake_gen_t *)ctx)->running = true;
    return 0;
}

static int gen_retarget(void *ctx, uint32_t cruise_pps)
{
    (void)ctx;
    (void)cruise_pps;
    return 0;
}

static int gen_halt(void *ctx, bool immediate)
{
    fake_gen_t *g = ctx;
    g->halts++;
    g->halted_immediately = immediate;
    if (immediate) {
        g->running = false;
    }
    return 0;
}

static int gen_state(void *ctx, tmc2209_run_state_t *out)
{
    *out = (tmc2209_run_state_t){ .running = ((fake_gen_t *)ctx)->running };
    return 0;
}

static const tmc2209_regval_t k_config[] = {
    { TMC2209_GCONF,      0x000000C0U },
    { TMC2209_SLAVECONF,  0x00000200U },
    { TMC2209_IHOLD_IRUN, 0x00081810U },
    { TMC2209_TPOWERDOWN, 0x00000014U },
    { TMC2209_TPWMTHRS,   0x000001F4U },
    { TMC2209_TCOOLTHRS,  0x000003E8U },
    { TMC2209_VACTUAL,    0x00000000U },
    { TMC2209_SGTHRS,     0x00000050U },
    { TMC2209_COOLCONF,   0x00010203U },
    { TMC2209_CHOPCONF,   0x14010053U },
};

static void trip_setup(void)
{
    memset(g_level, 0, sizeof(g_level));
    memset(&g_gen, 0, sizeof(g_gen));

    mock_init(&g_mock, &g_uart, 0, true);
    g_uart.timeout_ms = 10;
    g_uart.retries    = 0;

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_init(&g_dev, 0));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_attach_uart(&g_dev, &g_uart));

    g_lines = (tmc2209_lines_t){
        .read = board_read, .write = board_write, .ctx = NULL, .wired = TMC2209_LINES_ALL
    };
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_attach_lines(&g_dev, &g_lines));

    g_stepgen = (tmc2209_stepgen_t){
        .run          = gen_run,
        .retarget     = gen_retarget,
        .halt         = gen_halt,
        .state        = gen_state,
        .ctx          = &g_gen,
        .max_pps      = 40000,
        .min_pulse_ns = TMC2209_STEP_MIN_PULSE_NS,
    };
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_attach_stepgen(&g_dev, &g_stepgen));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_bringup(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));

    tmc2209_t  *devs[]  = { &g_dev };
    const char *names[] = { "capstan" };
    fake_devices_set(devs, names, 1);

    rpc_reset_registry();
    rpc_register(RPC_NS_RAW, rpc_raw_methods, RPC_RAW_COUNT);

    TEST_ASSERT_TRUE(rpc_untrip());
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_enable(&g_dev, true));
}

static void start_run(void)
{
    const tmc2209_movement_plan_t m = {
        .pulses = 1000, .pullin_pps = 100, .cruise_pps = 100, .accel_pps_s = 0
    };
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));
}

static bool enabled(void)
{
    bool on = false;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_is_enabled(&g_dev, &on));
    return on;
}

static rpc_status_t raw_call(uint8_t method, const void *args, size_t len)
{
    uint8_t ret[RPC_MAX_PAYLOAD];
    size_t  ret_len = 0;
    return rpc_dispatch(RPC_NS_RAW, method, args, len, ret, &ret_len);
}

static void test_an_idle_board_asks_for_no_keepalive(void)
{
    trip_setup();
    TEST_ASSERT_EQUAL_UINT16(RPC_KEEPALIVE_NONE, rpc_keepalive_within_ms(0));
}

static void test_a_run_in_flight_asks_for_a_keepalive(void)
{
    trip_setup();
    start_run();
    TEST_ASSERT_EQUAL_UINT16(RPC_KEEPALIVE_WITHIN_MS, rpc_keepalive_within_ms(0));
}

static void test_a_set_velocity_asks_for_a_keepalive(void)
{
    trip_setup();
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_set_velocity(&g_dev, 1000));
    TEST_ASSERT_EQUAL_UINT16(RPC_KEEPALIVE_WITHIN_MS, rpc_keepalive_within_ms(0));
}

static void test_silence_while_moving_trips_with_a_ramped_halt(void)
{
    trip_setup();
    start_run();
    (void)rpc_keepalive_within_ms(0);

    rpc_trip_update(RPC_KEEPALIVE_WITHIN_MS);
    TEST_ASSERT_EQUAL(RPC_TRIP_NONE, rpc_trip_reason());

    rpc_trip_update(RPC_KEEPALIVE_WITHIN_MS + 1U);
    TEST_ASSERT_EQUAL(RPC_TRIP_KEEPALIVE, rpc_trip_reason());
    TEST_ASSERT_EQUAL_INT(1, g_gen.halts);
    TEST_ASSERT_FALSE(g_gen.halted_immediately);
}

static void test_a_keepalive_puts_the_deadline_off(void)
{
    trip_setup();
    start_run();
    (void)rpc_keepalive_within_ms(0);

    rpc_keepalive_heard(400);
    rpc_trip_update(400 + RPC_KEEPALIVE_WITHIN_MS);
    TEST_ASSERT_EQUAL(RPC_TRIP_NONE, rpc_trip_reason());

    rpc_trip_update(401 + RPC_KEEPALIVE_WITHIN_MS);
    TEST_ASSERT_EQUAL(RPC_TRIP_KEEPALIVE, rpc_trip_reason());
}

static void test_silence_while_idle_trips_nothing(void)
{
    trip_setup();
    rpc_trip_update(100000);
    TEST_ASSERT_EQUAL(RPC_TRIP_NONE, rpc_trip_reason());
    TEST_ASSERT_TRUE(enabled());
}

static void test_a_ramped_trip_releases_once_the_run_ends(void)
{
    trip_setup();
    start_run();
    (void)rpc_keepalive_within_ms(0);
    rpc_trip_update(RPC_KEEPALIVE_WITHIN_MS + 1U);

    TEST_ASSERT_TRUE(enabled());

    g_gen.running = false;
    rpc_trip_update(RPC_KEEPALIVE_WITHIN_MS + 50U);
    TEST_ASSERT_FALSE(enabled());
}

static void test_a_tripped_board_asks_for_no_keepalive(void)
{
    trip_setup();
    start_run();
    rpc_trip(RPC_TRIP_REQUESTED, 0, false);
    TEST_ASSERT_EQUAL_UINT16(RPC_KEEPALIVE_NONE, rpc_keepalive_within_ms(0));
}

static void test_an_immediate_trip_releases_at_once(void)
{
    trip_setup();
    start_run();
    rpc_trip(RPC_TRIP_REQUESTED, 7, true);

    TEST_ASSERT_TRUE(g_gen.halted_immediately);
    TEST_ASSERT_FALSE(enabled());
    TEST_ASSERT_EQUAL(RPC_TRIP_REQUESTED, rpc_trip_reason());
    TEST_ASSERT_EQUAL_UINT8(7, rpc_trip_detail());
}

static void test_a_trip_stops_a_set_velocity(void)
{
    trip_setup();
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_set_velocity(&g_dev, 1000));
    rpc_trip(RPC_TRIP_REQUESTED, 0, false);

    uint32_t v = 1;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_read(&g_dev, TMC2209_VACTUAL, &v));
    TEST_ASSERT_EQUAL_UINT32(0, v);
    TEST_ASSERT_FALSE(enabled());
}

static void test_the_first_reason_is_kept(void)
{
    trip_setup();
    rpc_trip(RPC_TRIP_KEEPALIVE, 0, true);
    rpc_trip(RPC_TRIP_REQUESTED, 9, true);

    TEST_ASSERT_EQUAL(RPC_TRIP_KEEPALIVE, rpc_trip_reason());
    TEST_ASSERT_EQUAL_UINT8(0, rpc_trip_detail());
}

static void test_untripping_waits_for_the_release(void)
{
    trip_setup();
    start_run();
    rpc_trip(RPC_TRIP_REQUESTED, 0, false);

    TEST_ASSERT_FALSE(rpc_untrip());
    TEST_ASSERT_EQUAL(RPC_TRIP_REQUESTED, rpc_trip_reason());

    g_gen.running = false;
    TEST_ASSERT_TRUE(rpc_untrip());
    TEST_ASSERT_EQUAL(RPC_TRIP_NONE, rpc_trip_reason());
    TEST_ASSERT_FALSE(enabled());
}

static void test_a_tripped_board_refuses_to_move_or_enable(void)
{
    trip_setup();
    rpc_trip(RPC_TRIP_REQUESTED, 0, true);

    const rpc_raw_move_args move = { .idx = 0, .pulses = 10, .pullin_pps = 100, .cruise_pps = 100 };
    TEST_ASSERT_EQUAL(RPC_REFUSED, raw_call(RPC_RAW_MOVE, &move, sizeof(move)));

    const rpc_raw_enable_args on = { .idx = 0, .on = 1 };
    TEST_ASSERT_EQUAL(RPC_REFUSED, raw_call(RPC_RAW_ENABLE, &on, sizeof(on)));

    const rpc_raw_enable_args off = { .idx = 0, .on = 0 };
    TEST_ASSERT_EQUAL(RPC_OK, raw_call(RPC_RAW_ENABLE, &off, sizeof(off)));
}

static void test_an_untripped_board_moves_again(void)
{
    trip_setup();
    rpc_trip(RPC_TRIP_REQUESTED, 0, true);
    TEST_ASSERT_TRUE(rpc_untrip());

    const rpc_raw_enable_args on = { .idx = 0, .on = 1 };
    TEST_ASSERT_EQUAL(RPC_OK, raw_call(RPC_RAW_ENABLE, &on, sizeof(on)));
    TEST_ASSERT_TRUE(enabled());
}

static void test_an_unknown_velocity_on_an_enabled_driver_asks_for_a_keepalive(void)
{
    trip_setup();
    tmc2209_invalidate_owned(&g_dev);
    TEST_ASSERT_EQUAL_UINT16(RPC_KEEPALIVE_WITHIN_MS, rpc_keepalive_within_ms(0));
}

static void test_an_unknown_velocity_on_a_disabled_driver_asks_for_none(void)
{
    trip_setup();
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_enable(&g_dev, false));
    tmc2209_invalidate_owned(&g_dev);
    TEST_ASSERT_EQUAL_UINT16(RPC_KEEPALIVE_NONE, rpc_keepalive_within_ms(0));
}

static void test_an_unreachable_driver_does_not_hold_up_the_untrip(void)
{
    trip_setup();
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_set_velocity(&g_dev, 1000));
    g_mock.drop_reply = 1000;

    rpc_trip(RPC_TRIP_REQUESTED, 0, false);
    TEST_ASSERT_TRUE(rpc_untrip());
    TEST_ASSERT_FALSE(enabled());
}

void run_trip_tests(void)
{
    RUN_TEST(test_an_idle_board_asks_for_no_keepalive);
    RUN_TEST(test_a_run_in_flight_asks_for_a_keepalive);
    RUN_TEST(test_a_set_velocity_asks_for_a_keepalive);
    RUN_TEST(test_an_unknown_velocity_on_an_enabled_driver_asks_for_a_keepalive);
    RUN_TEST(test_an_unknown_velocity_on_a_disabled_driver_asks_for_none);
    RUN_TEST(test_silence_while_moving_trips_with_a_ramped_halt);
    RUN_TEST(test_a_keepalive_puts_the_deadline_off);
    RUN_TEST(test_silence_while_idle_trips_nothing);
    RUN_TEST(test_a_ramped_trip_releases_once_the_run_ends);
    RUN_TEST(test_a_tripped_board_asks_for_no_keepalive);
    RUN_TEST(test_an_immediate_trip_releases_at_once);
    RUN_TEST(test_a_trip_stops_a_set_velocity);
    RUN_TEST(test_the_first_reason_is_kept);
    RUN_TEST(test_untripping_waits_for_the_release);
    RUN_TEST(test_an_unreachable_driver_does_not_hold_up_the_untrip);
    RUN_TEST(test_a_tripped_board_refuses_to_move_or_enable);
    RUN_TEST(test_an_untripped_board_moves_again);
}
