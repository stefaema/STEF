/*
 * test_stepgen.c: motion, against a fake pulse source and a fake board.
 *
 * The fake stepgen emits nothing. It records the plan it was handed and lets
 * the test say how many pulses came out and when the run ended, which is the
 * only way to exercise an asynchronous backend without a clock. What it cannot
 * test is whether a real ramp keeps a real motor in sync; that is per backend
 * and needs hardware.
 *
 * Two themes. Direction is a fact about the configuration and not about the
 * wiring, so GCONF.shaft has to reach the DIR pin and an unknown GCONF has to
 * stop the move outright. And the odometer must count each run exactly once:
 * polling it during a run must not accumulate, and polling it after must not
 * accumulate either.
 */

#include "unity.h"
#include "mock_tmc2209.h"

#include <string.h>

/* GCONF with pdn_disable and mstep_reg_select, as any working driver needs. */
#define CFG_GCONF       0x000000C0u
/* The same, with shaft set: same board, opposite rotation. */
#define CFG_GCONF_SHAFT 0x000000C8u

static tmc2209_regval_t g_config[] = {
    { TMC2209_GCONF,      CFG_GCONF    },
    { TMC2209_SLAVECONF,  0x00000200u  },
    { TMC2209_IHOLD_IRUN, 0x00081810u  },
    { TMC2209_TPOWERDOWN, 0x00000014u  },
    { TMC2209_TPWMTHRS,   0x000001F4u  },
    { TMC2209_TCOOLTHRS,  0x000003E8u  },
    { TMC2209_VACTUAL,    0x00000000u  },
    { TMC2209_SGTHRS,     0x00000050u  },
    { TMC2209_COOLCONF,   0x00010203u  },
    { TMC2209_CHOPCONF,   0x14010053u  },
};

/* ── The fakes ──────────────────────────────────────────────────────────── */

typedef struct {
    tmc2209_run_t plan;          /* what the last run() was asked for */
    unsigned      runs;
    unsigned      halts;
    unsigned      retargets;
    uint32_t      last_retarget;
    bool          last_halt_immediate;

    uint32_t emitted;
    uint32_t rate_pps;
    bool     running;

    bool dir_at_run;             /* the DIR level as it stood when run() was called */
    int  fail_run, fail_state, fail_halt, fail_retarget;
} fake_gen_t;

typedef struct {
    bool     level[TMC2209_LINE_COUNT];
    unsigned writes[TMC2209_LINE_COUNT];
} fake_board_t;

static mock_dev_t        g_mock;
static tmc2209_port_t    g_port;
static tmc2209_bus_t     g_bus;
static fake_board_t      g_board;
static tmc2209_lines_t   g_lines;
static fake_gen_t        g_gen;
static tmc2209_stepgen_t g_stepgen;
static tmc2209_t         g_dev;

static int board_read(void *ctx, tmc2209_line_t line)
{
    return ((fake_board_t *)ctx)->level[line] ? 1 : 0;
}

static int board_write(void *ctx, tmc2209_line_t line, bool level)
{
    fake_board_t *b = (fake_board_t *)ctx;
    b->writes[line]++;
    b->level[line] = level;
    return 0;
}

static int gen_run(void *ctx, const tmc2209_run_t *plan)
{
    fake_gen_t *g = (fake_gen_t *)ctx;
    if (g->fail_run) {
        return -1;
    }
    g->plan       = *plan;
    g->runs++;
    g->emitted    = 0;
    g->rate_pps   = plan->pullin_pps;
    g->running    = true;
    g->dir_at_run = g_board.level[TMC2209_LINE_DIR];
    return 0;
}

static int gen_retarget(void *ctx, uint32_t cruise_pps)
{
    fake_gen_t *g = (fake_gen_t *)ctx;
    if (g->fail_retarget) {
        return -1;
    }
    g->retargets++;
    g->last_retarget = cruise_pps;
    g->rate_pps      = cruise_pps;
    return 0;
}

static int gen_halt(void *ctx, bool immediate)
{
    fake_gen_t *g = (fake_gen_t *)ctx;
    if (g->fail_halt) {
        return -1;
    }
    g->halts++;
    g->last_halt_immediate = immediate;
    /* A ramped halt keeps stepping, which is exactly what the library must not
       assume away. Only the immediate form ends the run here. */
    if (immediate) {
        g->running = false;
    }
    return 0;
}

static int gen_state(void *ctx, tmc2209_run_state_t *out)
{
    fake_gen_t *g = (fake_gen_t *)ctx;
    if (g->fail_state) {
        return -1;
    }
    out->emitted  = g->emitted;
    out->rate_pps = g->rate_pps;
    out->running  = g->running;
    return 0;
}

/* What a real backend does on its own: pulses come out, then the run ends. */
static void gen_finish(uint32_t emitted)
{
    g_gen.emitted  = emitted;
    g_gen.rate_pps = 0;
    g_gen.running  = false;
}

static void setup_ready(uint32_t gconf)
{
    memset(&g_board, 0, sizeof g_board);
    memset(&g_gen, 0, sizeof g_gen);

    mock_init(&g_mock, &g_port, 0, true);
    g_bus.port       = &g_port;
    g_bus.timeout_ms = 10;
    g_bus.retries    = 1;

    g_lines.read  = board_read;
    g_lines.write = board_write;
    g_lines.ctx   = &g_board;
    g_lines.wired = TMC2209_LINES_ALL;

    g_stepgen.run          = gen_run;
    g_stepgen.retarget     = gen_retarget;
    g_stepgen.halt         = gen_halt;
    g_stepgen.state        = gen_state;
    g_stepgen.ctx          = &g_gen;
    g_stepgen.max_pps      = 40000;
    g_stepgen.min_pulse_ns = TMC2209_STEP_MIN_PULSE_NS;

    g_config[0].value = gconf;

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_init(&g_dev, 0));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_attach_bus(&g_dev, &g_bus));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_attach_lines(&g_dev, &g_lines));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_attach_stepgen(&g_dev, &g_stepgen));
    TEST_ASSERT_EQUAL(TMC2209_OK,
        tmc2209_bringup(&g_dev, g_config, TMC2209_NELEM(g_config), NULL));
}

static tmc2209_move_t a_move(bool forward, uint32_t pulses)
{
    const tmc2209_move_t m = {
        .forward     = forward,
        .pulses      = pulses,
        .pullin_pps  = 400,
        .cruise_pps  = 20000,
        .accel_pps_s = 100000,
    };
    return m;
}

static tmc2209_motion_t motion_now(void)
{
    tmc2209_motion_t motion;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_motion(&g_dev, &motion));
    return motion;
}

/* ── Attachment ─────────────────────────────────────────────────────────── */

static void test_a_device_without_a_stepgen_refuses_every_motion_call(void)
{
    setup_ready(CFG_GCONF);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_attach_stepgen(&g_dev, NULL));

    const tmc2209_move_t m = a_move(true, 100);
    tmc2209_motion_t motion;

    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND, tmc2209_move(&g_dev, &m));
    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND, tmc2209_halt(&g_dev, true));
    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND, tmc2209_retarget(&g_dev, 1000));
    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND, tmc2209_motion(&g_dev, &motion));
    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND, tmc2209_zero_position(&g_dev));
    TEST_ASSERT_EQUAL(0u, g_gen.runs);
}

/* Half a backend is not a backend, on the same terms as the port and the
   lines: reject it at the seam rather than at the first pulse. */
static void test_attach_rejects_an_incomplete_backend(void)
{
    setup_ready(CFG_GCONF);

    tmc2209_stepgen_t half = g_stepgen;
    half.run = NULL;
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_attach_stepgen(&g_dev, &half));

    half = g_stepgen;
    half.state = NULL;
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_attach_stepgen(&g_dev, &half));

    half = g_stepgen;
    half.halt = NULL;
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_attach_stepgen(&g_dev, &half));

    half = g_stepgen;
    half.retarget = NULL;
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_attach_stepgen(&g_dev, &half));
}

/* The pulse width is the part's requirement, so a backend that cannot meet it
   is refused here rather than producing edges the driver never registers. */
static void test_attach_rejects_a_backend_that_pulses_too_narrowly(void)
{
    setup_ready(CFG_GCONF);

    tmc2209_stepgen_t narrow = g_stepgen;
    narrow.min_pulse_ns = TMC2209_STEP_MIN_PULSE_NS - 1u;
    TEST_ASSERT_EQUAL(TMC2209_ERR_RATE, tmc2209_attach_stepgen(&g_dev, &narrow));

    tmc2209_stepgen_t still = g_stepgen;
    still.max_pps = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_attach_stepgen(&g_dev, &still));
}

/* Swapping the source out mid-run would leave the count in a backend nothing
   points at any more, and the odometer short by that much for good. */
static void test_attach_is_refused_while_a_run_is_in_flight(void)
{
    setup_ready(CFG_GCONF);
    const tmc2209_move_t m = a_move(true, 1000);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));

    TEST_ASSERT_EQUAL(TMC2209_ERR_BUSY, tmc2209_attach_stepgen(&g_dev, NULL));
}

/* ── Direction ──────────────────────────────────────────────────────────── */

/* The ordering the part requires, and the reason this layer exists at all: a
   caller driving both backends itself could get it backwards silently. */
static void test_dir_is_set_before_the_first_pulse(void)
{
    setup_ready(CFG_GCONF);
    const tmc2209_move_t m = a_move(true, 1000);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));
    TEST_ASSERT_EQUAL(1u, g_board.writes[TMC2209_LINE_DIR]);
    TEST_ASSERT_TRUE(g_gen.dir_at_run);
}

/* shaft flips which phase order winds film forward, so the same request has to
   reach the pin as the opposite level. Asserting the level rather than the
   round trip is what catches an implementation that is consistently wrong. */
static void test_gconf_shaft_inverts_the_dir_level(void)
{
    setup_ready(CFG_GCONF_SHAFT);
    const tmc2209_move_t m = a_move(true, 1000);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));
    TEST_ASSERT_FALSE(g_gen.dir_at_run);
}

/* An unknown shaft bit is an unknown direction, and with no encoder a move the
   wrong way is not detected, it is recorded as progress. */
static void test_an_unknown_gconf_stops_the_move(void)
{
    setup_ready(CFG_GCONF);
    tmc2209_invalidate_owned(&g_dev);

    const tmc2209_move_t m = a_move(true, 1000);
    TEST_ASSERT_EQUAL(TMC2209_ERR_INVALID_SLOT, tmc2209_move(&g_dev, &m));
    TEST_ASSERT_EQUAL(0u, g_gen.runs);
    TEST_ASSERT_EQUAL(0u, g_board.writes[TMC2209_LINE_DIR]);
}

/* The odometer is in forward pulses whichever level that took, so a reversed
   board or a rewritten shaft bit cannot make the position drift. */
static void test_the_odometer_is_signed_by_intent_not_by_level(void)
{
    setup_ready(CFG_GCONF_SHAFT);
    const tmc2209_move_t back = a_move(false, 500);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &back));
    TEST_ASSERT_TRUE(g_gen.dir_at_run);          /* shaft inverted the level */
    gen_finish(500);
    TEST_ASSERT_EQUAL_INT32(-500, motion_now().position);  /* not the sign */
}

/* ── The odometer ───────────────────────────────────────────────────────── */

static void test_a_finished_run_lands_in_the_position(void)
{
    setup_ready(CFG_GCONF);
    const tmc2209_move_t m = a_move(true, 4000);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));
    gen_finish(4000);

    const tmc2209_motion_t motion = motion_now();
    TEST_ASSERT_FALSE(motion.running);
    TEST_ASSERT_EQUAL_UINT32(4000, motion.emitted);
    TEST_ASSERT_EQUAL_INT32(4000, motion.position);
}

/* Every run polls this repeatedly while it waits. A fold that ran per poll
   would give a position that climbs while the motor stands still. */
static void test_polling_a_finished_run_folds_it_once(void)
{
    setup_ready(CFG_GCONF);
    const tmc2209_move_t m = a_move(true, 4000);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));
    gen_finish(4000);

    for (int i = 0; i < 5; i++) {
        TEST_ASSERT_EQUAL_INT32(4000, motion_now().position);
    }
}

/* The convergence loop reads position while the move is still going, so the
   pulses so far have to be visible without being committed twice. */
static void test_a_run_in_flight_shows_its_progress(void)
{
    setup_ready(CFG_GCONF);
    const tmc2209_move_t m = a_move(true, 4000);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));

    g_gen.emitted = 1500;
    tmc2209_motion_t motion = motion_now();
    TEST_ASSERT_TRUE(motion.running);
    TEST_ASSERT_EQUAL_INT32(1500, motion.position);

    gen_finish(4000);
    TEST_ASSERT_EQUAL_INT32(4000, motion_now().position);
}

static void test_successive_runs_accumulate_with_sign(void)
{
    setup_ready(CFG_GCONF);

    const tmc2209_move_t fwd = a_move(true, 1000);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &fwd));
    gen_finish(1000);
    TEST_ASSERT_EQUAL_INT32(1000, motion_now().position);

    const tmc2209_move_t back = a_move(false, 400);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &back));
    gen_finish(400);
    TEST_ASSERT_EQUAL_INT32(600, motion_now().position);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &fwd));
    gen_finish(1000);
    TEST_ASSERT_EQUAL_INT32(1600, motion_now().position);
}

/* An aborted run moved as far as it moved. The count is the only record of it,
   so a halt that discarded the partial travel would lose the film's position
   at exactly the moment something already went wrong. */
static void test_an_aborted_run_keeps_the_pulses_it_did_emit(void)
{
    setup_ready(CFG_GCONF);
    const tmc2209_move_t m = a_move(true, 4000);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));

    g_gen.emitted = 1234;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_halt(&g_dev, true));
    TEST_ASSERT_EQUAL_INT32(1234, motion_now().position);
}

/* A ramped halt is still emitting when halt() returns. Folding there would
   commit a count the motor has not finished producing. */
static void test_a_ramped_halt_settles_only_once_the_pulses_stop(void)
{
    setup_ready(CFG_GCONF);
    const tmc2209_move_t m = a_move(true, 0);   /* unbounded */
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));

    g_gen.emitted = 900;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_halt(&g_dev, false));
    TEST_ASSERT_TRUE(motion_now().running);

    gen_finish(1100);                           /* it kept stepping while ramping down */
    TEST_ASSERT_EQUAL_INT32(1100, motion_now().position);
}

static void test_zeroing_is_refused_while_moving(void)
{
    setup_ready(CFG_GCONF);
    const tmc2209_move_t m = a_move(true, 4000);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));

    g_gen.emitted = 100;
    TEST_ASSERT_EQUAL(TMC2209_ERR_BUSY, tmc2209_zero_position(&g_dev));

    gen_finish(4000);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_zero_position(&g_dev));
    TEST_ASSERT_EQUAL_INT32(0, motion_now().position);
}

/* ── The profile ────────────────────────────────────────────────────────── */

/* The plan reaches the backend untouched. Nothing here reinterprets a rate,
   because a move that ran slower than believed is a position error. */
static void test_the_plan_reaches_the_backend_unaltered(void)
{
    setup_ready(CFG_GCONF);
    const tmc2209_move_t m = a_move(true, 4000);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));

    TEST_ASSERT_EQUAL_UINT32(4000,   g_gen.plan.pulses);
    TEST_ASSERT_EQUAL_UINT32(400,    g_gen.plan.pullin_pps);
    TEST_ASSERT_EQUAL_UINT32(20000,  g_gen.plan.cruise_pps);
    TEST_ASSERT_EQUAL_UINT32(100000, g_gen.plan.accel_pps_s);
}

/* A profile that contradicts itself is a bad argument. A profile the board
   cannot reach is not, and the two carry different instructions: fix the
   request, as against buy a faster board or accept a slower scan. */
static void test_an_incoherent_profile_is_refused(void)
{
    setup_ready(CFG_GCONF);
    tmc2209_move_t m = a_move(true, 100);

    m.pullin_pps = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_move(&g_dev, &m));

    m = a_move(true, 100);
    m.cruise_pps = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_move(&g_dev, &m));

    m = a_move(true, 100);
    m.cruise_pps = m.pullin_pps - 1u;
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_move(&g_dev, &m));

    /* A ramp is required to reach cruise, and none was allowed. */
    m = a_move(true, 100);
    m.accel_pps_s = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_move(&g_dev, &m));

    TEST_ASSERT_EQUAL(0u, g_gen.runs);
}

/* Cruising at the pull-in rate needs no ramp, so no accel is coherent there. */
static void test_a_flat_profile_needs_no_ramp(void)
{
    setup_ready(CFG_GCONF);
    tmc2209_move_t m = a_move(true, 100);
    m.cruise_pps  = m.pullin_pps;
    m.accel_pps_s = 0;

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));
}

static void test_a_rate_the_board_cannot_emit_is_refused(void)
{
    setup_ready(CFG_GCONF);
    tmc2209_move_t m = a_move(true, 100);
    m.cruise_pps = g_stepgen.max_pps + 1u;

    TEST_ASSERT_EQUAL(TMC2209_ERR_RATE, tmc2209_move(&g_dev, &m));
    TEST_ASSERT_EQUAL(0u, g_gen.runs);
}

/* ── Preconditions ──────────────────────────────────────────────────────── */

static void test_a_second_move_while_running_is_refused(void)
{
    setup_ready(CFG_GCONF);
    const tmc2209_move_t m = a_move(true, 4000);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));

    TEST_ASSERT_EQUAL(TMC2209_ERR_BUSY, tmc2209_move(&g_dev, &m));
    TEST_ASSERT_EQUAL(1u, g_gen.runs);
    TEST_ASSERT_EQUAL(1u, g_board.writes[TMC2209_LINE_DIR]);
}

/* VACTUAL takes the driver off its STEP pin silently. Pulses would still be
   emitted and still be counted, which is a position the film never reached. */
static void test_a_move_under_the_velocity_generator_is_refused(void)
{
    setup_ready(CFG_GCONF);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_set_velocity(&g_dev, 1000));

    const tmc2209_move_t m = a_move(true, 4000);
    TEST_ASSERT_EQUAL(TMC2209_ERR_ACCESS, tmc2209_move(&g_dev, &m));
    TEST_ASSERT_EQUAL(0u, g_gen.runs);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_set_velocity(&g_dev, 0));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));
}

/* DIR is the one line a move cannot do without, and a board that leaves it
   unwired says so rather than stepping in whichever direction the pin floats. */
static void test_a_move_without_dir_is_refused(void)
{
    setup_ready(CFG_GCONF);
    g_lines.wired = TMC2209_LINES_ALL & (uint8_t)~TMC2209_LINE_BIT(TMC2209_LINE_DIR);

    const tmc2209_move_t m = a_move(true, 4000);
    TEST_ASSERT_EQUAL(TMC2209_ERR_UNWIRED, tmc2209_move(&g_dev, &m));
    TEST_ASSERT_EQUAL(0u, g_gen.runs);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_attach_lines(&g_dev, NULL));
    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND, tmc2209_move(&g_dev, &m));
}

/* ── Retarget ───────────────────────────────────────────────────────────── */

static void test_retarget_changes_a_run_in_flight(void)
{
    setup_ready(CFG_GCONF);
    const tmc2209_move_t m = a_move(true, 0);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_retarget(&g_dev, 12000));
    TEST_ASSERT_EQUAL_UINT32(12000, g_gen.last_retarget);
    TEST_ASSERT_EQUAL_UINT32(12000, motion_now().rate_pps);
    TEST_ASSERT_EQUAL(1u, g_gen.runs);     /* not a restart */
}

/* Pull-in bounds starting and stopping, not running. A motor already turning
   can be ramped below it, which is how a tension loop backs off. */
static void test_retarget_may_go_below_the_pullin_rate(void)
{
    setup_ready(CFG_GCONF);
    const tmc2209_move_t m = a_move(true, 0);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_retarget(&g_dev, m.pullin_pps / 2u));
}

static void test_retarget_needs_something_to_retarget(void)
{
    setup_ready(CFG_GCONF);
    TEST_ASSERT_EQUAL(TMC2209_ERR_IDLE, tmc2209_retarget(&g_dev, 12000));

    const tmc2209_move_t m = a_move(true, 4000);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));
    gen_finish(4000);
    TEST_ASSERT_EQUAL(TMC2209_ERR_IDLE, tmc2209_retarget(&g_dev, 12000));

    TEST_ASSERT_EQUAL(0u, g_gen.retargets);
}

static void test_retarget_refuses_a_rate_the_board_cannot_emit(void)
{
    setup_ready(CFG_GCONF);
    const tmc2209_move_t m = a_move(true, 0);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));

    TEST_ASSERT_EQUAL(TMC2209_ERR_RATE, tmc2209_retarget(&g_dev, g_stepgen.max_pps + 1u));
    TEST_ASSERT_EQUAL(TMC2209_ERR_RATE, tmc2209_retarget(&g_dev, 0));
    TEST_ASSERT_EQUAL(0u, g_gen.retargets);
}

/* ── Halt ───────────────────────────────────────────────────────────────── */

static void test_halting_an_idle_driver_does_nothing_and_succeeds(void)
{
    setup_ready(CFG_GCONF);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_halt(&g_dev, true));
    TEST_ASSERT_EQUAL_INT32(0, motion_now().position);
}

static void test_halt_passes_on_which_kind_was_asked_for(void)
{
    setup_ready(CFG_GCONF);
    const tmc2209_move_t m = a_move(true, 0);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_halt(&g_dev, false));
    TEST_ASSERT_FALSE(g_gen.last_halt_immediate);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_halt(&g_dev, true));
    TEST_ASSERT_TRUE(g_gen.last_halt_immediate);
}

/* ── Pin ownership ──────────────────────────────────────────────────────── */

/* One pin, one owner. A level write racing a peripheral is decided by whichever
   driver the board happens to use, which is not a decision at all. */
static void test_a_stepgen_takes_the_step_pin(void)
{
    setup_ready(CFG_GCONF);

    TEST_ASSERT_EQUAL(TMC2209_ERR_ACCESS, tmc2209_line_write(&g_dev, TMC2209_LINE_STEP, true));
    TEST_ASSERT_EQUAL(0u, g_board.writes[TMC2209_LINE_STEP]);

    /* Reading the level disturbs nothing, and is the diagnostic that catches a
       peripheral that stopped mid-pulse. */
    bool level = true;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_line_read(&g_dev, TMC2209_LINE_STEP, &level));

    /* Without one, the board owns the pin again. */
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_attach_stepgen(&g_dev, NULL));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_line_write(&g_dev, TMC2209_LINE_STEP, true));
}

/* The other three lines are untouched by any of this. ENN in particular stays
   available, because it is what an emergency stop reaches for. */
static void test_a_stepgen_leaves_the_other_lines_alone(void)
{
    setup_ready(CFG_GCONF);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_enable(&g_dev, true));
    TEST_ASSERT_FALSE(g_board.level[TMC2209_LINE_ENN]);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_line_write(&g_dev, TMC2209_LINE_DIR, true));
}

/* ── Backend failure ────────────────────────────────────────────────────── */

/* A backend that refuses the run has not moved anything, so the library must
   not go on believing a run is in flight. */
static void test_a_refused_run_leaves_nothing_in_flight(void)
{
    setup_ready(CFG_GCONF);
    g_gen.fail_run = 1;

    const tmc2209_move_t m = a_move(true, 4000);
    TEST_ASSERT_EQUAL(TMC2209_ERR_IO, tmc2209_move(&g_dev, &m));

    g_gen.fail_run = 0;
    TEST_ASSERT_FALSE(motion_now().running);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));
}

static void test_a_backend_failure_yields_no_position(void)
{
    setup_ready(CFG_GCONF);
    tmc2209_motion_t motion;

    g_gen.fail_state = 1;
    TEST_ASSERT_EQUAL(TMC2209_ERR_IO, tmc2209_motion(&g_dev, &motion));

    g_gen.fail_state = 0;
    g_gen.fail_halt  = 1;
    TEST_ASSERT_EQUAL(TMC2209_ERR_IO, tmc2209_halt(&g_dev, true));
}

static void test_null_arguments_are_bad_arguments(void)
{
    setup_ready(CFG_GCONF);
    const tmc2209_move_t m = a_move(true, 100);

    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_move(&g_dev, NULL));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_move(NULL, &m));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_motion(&g_dev, NULL));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_halt(NULL, true));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_retarget(NULL, 1000));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_zero_position(NULL));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_attach_stepgen(NULL, &g_stepgen));
}

/* Construction attaches nothing, so a device that never saw a stepgen has an
   odometer at rest and no run to settle. */
static void test_init_leaves_the_stepgen_detached(void)
{
    setup_ready(CFG_GCONF);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_init(&g_dev, 0));

    tmc2209_motion_t motion;
    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND, tmc2209_motion(&g_dev, &motion));
    TEST_ASSERT_EQUAL_INT32(0, g_dev.position);
}

void run_stepgen_tests(void)
{
    RUN_TEST(test_a_device_without_a_stepgen_refuses_every_motion_call);
    RUN_TEST(test_attach_rejects_an_incomplete_backend);
    RUN_TEST(test_attach_rejects_a_backend_that_pulses_too_narrowly);
    RUN_TEST(test_attach_is_refused_while_a_run_is_in_flight);
    RUN_TEST(test_init_leaves_the_stepgen_detached);

    RUN_TEST(test_dir_is_set_before_the_first_pulse);
    RUN_TEST(test_gconf_shaft_inverts_the_dir_level);
    RUN_TEST(test_an_unknown_gconf_stops_the_move);
    RUN_TEST(test_the_odometer_is_signed_by_intent_not_by_level);

    RUN_TEST(test_a_finished_run_lands_in_the_position);
    RUN_TEST(test_polling_a_finished_run_folds_it_once);
    RUN_TEST(test_a_run_in_flight_shows_its_progress);
    RUN_TEST(test_successive_runs_accumulate_with_sign);
    RUN_TEST(test_an_aborted_run_keeps_the_pulses_it_did_emit);
    RUN_TEST(test_a_ramped_halt_settles_only_once_the_pulses_stop);
    RUN_TEST(test_zeroing_is_refused_while_moving);

    RUN_TEST(test_the_plan_reaches_the_backend_unaltered);
    RUN_TEST(test_an_incoherent_profile_is_refused);
    RUN_TEST(test_a_flat_profile_needs_no_ramp);
    RUN_TEST(test_a_rate_the_board_cannot_emit_is_refused);

    RUN_TEST(test_a_second_move_while_running_is_refused);
    RUN_TEST(test_a_move_under_the_velocity_generator_is_refused);
    RUN_TEST(test_a_move_without_dir_is_refused);

    RUN_TEST(test_retarget_changes_a_run_in_flight);
    RUN_TEST(test_retarget_may_go_below_the_pullin_rate);
    RUN_TEST(test_retarget_needs_something_to_retarget);
    RUN_TEST(test_retarget_refuses_a_rate_the_board_cannot_emit);

    RUN_TEST(test_halting_an_idle_driver_does_nothing_and_succeeds);
    RUN_TEST(test_halt_passes_on_which_kind_was_asked_for);

    RUN_TEST(test_a_stepgen_takes_the_step_pin);
    RUN_TEST(test_a_stepgen_leaves_the_other_lines_alone);

    RUN_TEST(test_a_refused_run_leaves_nothing_in_flight);
    RUN_TEST(test_a_backend_failure_yields_no_position);
    RUN_TEST(test_null_arguments_are_bad_arguments);
}
