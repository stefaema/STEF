/*
 * test_stepgen.c: motion, against a fake pulse source and a fake board.
 *
 * The fake stepgen emits nothing. It records the plan it was handed and lets
 * the test say how many pulses came out and when the run ended, which is the
 * only way to exercise an asynchronous backend without a clock. What it cannot
 * test is whether a real ramp keeps a real motor in sync; that is per backend
 * and needs hardware.
 *
 * Two themes. A move states both halves of its direction, the DIR level and the
 * shaft bit it is counting on, and a driver holding the other shaft bit refuses
 * the run rather than winding film the wrong way. And a run's count must
 * survive long enough to be collected: the backend holds one, so a second move
 * before anyone read the first is refused.
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

/* The shaft bit setup_ready() configured, so a_move() declares what is actually
   in effect and the mismatch tests are the ones that state otherwise. */
static bool              g_shaft;

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
    g_shaft           = tmc2209_gconf_decode(gconf).shaft;

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_init(&g_dev, 0));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_attach_bus(&g_dev, &g_bus));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_attach_lines(&g_dev, &g_lines));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_attach_stepgen(&g_dev, &g_stepgen));
    TEST_ASSERT_EQUAL(TMC2209_OK,
        tmc2209_bringup(&g_dev, g_config, TMC2209_NELEM(g_config), NULL));
}

static tmc2209_move_t a_move(bool dir, uint32_t pulses)
{
    const tmc2209_move_t m = {
        .dir         = dir,
        .shaft       = g_shaft,
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
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_poll_motion(&g_dev, &motion));
    return motion;
}

/* What a caller does between runs: collect the count so the next move is
   allowed to overwrite it. */
static uint32_t collect_count(void)
{
    return motion_now().emitted;
}

/* ── Attachment ─────────────────────────────────────────────────────────── */

static void test_a_device_without_a_stepgen_refuses_every_motion_call(void)
{
    setup_ready(CFG_GCONF);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_attach_stepgen(&g_dev, NULL));

    const tmc2209_move_t m = a_move(true, 100);
    tmc2209_motion_t motion;
    bool running = false;

    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND, tmc2209_move(&g_dev, &m));
    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND, tmc2209_halt(&g_dev, true));
    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND, tmc2209_retarget(&g_dev, 1000));
    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND, tmc2209_poll_motion(&g_dev, &motion));
    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND, tmc2209_is_running(&g_dev, &running));
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

/* The level asked for is the level driven, whatever shaft happens to be. What
   the pair means for the film is the layer above's to decide, and an
   implementation that quietly reinterpreted it would take that away. */
static void test_the_dir_level_reaches_the_pin_uninterpreted(void)
{
    setup_ready(CFG_GCONF_SHAFT);
    const tmc2209_move_t m = a_move(true, 1000);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));
    TEST_ASSERT_TRUE(g_gen.dir_at_run);
}

/* A move declares the shaft bit it is counting on. If the driver holds the
   other one, the same DIR level winds film the opposite way, so the run is
   refused rather than started on a belief that is already wrong. */
static void test_a_move_that_misreads_the_shaft_bit_is_refused(void)
{
    setup_ready(CFG_GCONF);

    tmc2209_move_t m = a_move(true, 1000);
    m.shaft = !g_shaft;

    TEST_ASSERT_EQUAL(TMC2209_ERR_MISMATCH, tmc2209_move(&g_dev, &m));
    TEST_ASSERT_EQUAL(0u, g_gen.runs);
    TEST_ASSERT_EQUAL(0u, g_board.writes[TMC2209_LINE_DIR]);
}

/* And the same board with shaft set accepts the declaration that matches it. */
static void test_a_move_that_declares_the_shaft_bit_correctly_runs(void)
{
    setup_ready(CFG_GCONF_SHAFT);

    tmc2209_move_t m = a_move(false, 1000);
    m.shaft = true;

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

/* ── The count ──────────────────────────────────────────────────────────── */

static void test_a_finished_run_reports_its_count(void)
{
    setup_ready(CFG_GCONF);
    const tmc2209_move_t m = a_move(true, 4000);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));
    gen_finish(4000);

    const tmc2209_motion_t motion = motion_now();
    TEST_ASSERT_FALSE(motion.running);
    TEST_ASSERT_EQUAL_UINT32(4000, motion.emitted);
}

/* Every run polls this repeatedly while it waits, so polling has to be a
   question and not a transaction: the same count, however often it is asked
   for. */
static void test_polling_a_finished_run_reports_the_same_count(void)
{
    setup_ready(CFG_GCONF);
    const tmc2209_move_t m = a_move(true, 4000);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));
    gen_finish(4000);

    for (int i = 0; i < 5; i++) {
        TEST_ASSERT_EQUAL_UINT32(4000, motion_now().emitted);
    }
}

/* The control loop reads the count while the move is still going, so the pulses
   so far have to be visible before the run is over. */
static void test_a_run_in_flight_shows_its_progress(void)
{
    setup_ready(CFG_GCONF);
    const tmc2209_move_t m = a_move(true, 4000);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));

    g_gen.emitted = 1500;
    tmc2209_motion_t motion = motion_now();
    TEST_ASSERT_TRUE(motion.running);
    TEST_ASSERT_EQUAL_UINT32(1500, motion.emitted);

    gen_finish(4000);
    TEST_ASSERT_EQUAL_UINT32(4000, motion_now().emitted);
}

/* A backend holds one run's count, so a second move would overwrite a total
   nobody has seen, and those pulses went into film. */
static void test_a_move_needs_the_last_count_collected(void)
{
    setup_ready(CFG_GCONF);
    const tmc2209_move_t m = a_move(true, 1000);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));
    gen_finish(1000);

    TEST_ASSERT_EQUAL(TMC2209_ERR_UNREAD, tmc2209_move(&g_dev, &m));
    TEST_ASSERT_EQUAL(1u, g_gen.runs);

    TEST_ASSERT_EQUAL_UINT32(1000, collect_count());
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));
    TEST_ASSERT_EQUAL(2u, g_gen.runs);
}

/* Polling mid-run settles nothing, because the total being acknowledged does
   not exist yet. A loop that watched a run go by and then started another one
   would otherwise lose the count it never actually saw. */
static void test_polling_mid_run_does_not_pay_the_debt(void)
{
    setup_ready(CFG_GCONF);
    const tmc2209_move_t m = a_move(true, 1000);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));
    g_gen.emitted = 500;
    TEST_ASSERT_TRUE(motion_now().running);

    gen_finish(1000);
    TEST_ASSERT_EQUAL(TMC2209_ERR_UNREAD, tmc2209_move(&g_dev, &m));
}

/* The first move owes nothing, and a refused one owes nothing either. */
static void test_a_first_move_owes_no_count(void)
{
    setup_ready(CFG_GCONF);
    const tmc2209_move_t m = a_move(true, 1000);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));
    TEST_ASSERT_EQUAL(1u, g_gen.runs);
}

/* An aborted run moved as far as it moved. The count is the only record of it,
   so a halt that discarded the partial travel would lose how far the film went
   at exactly the moment something already went wrong. */
static void test_an_aborted_run_keeps_the_pulses_it_did_emit(void)
{
    setup_ready(CFG_GCONF);
    const tmc2209_move_t m = a_move(true, 4000);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));

    g_gen.emitted = 1234;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_halt(&g_dev, true));
    TEST_ASSERT_EQUAL_UINT32(1234, motion_now().emitted);
}

/* A ramped halt is still emitting when halt() returns, so the run is not over
   and its count is not final. */
static void test_a_ramped_halt_is_not_over_until_the_pulses_stop(void)
{
    setup_ready(CFG_GCONF);
    const tmc2209_move_t m = a_move(true, 0);   /* unbounded */
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));

    g_gen.emitted = 900;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_halt(&g_dev, false));
    TEST_ASSERT_TRUE(motion_now().running);

    gen_finish(1100);                           /* it kept stepping while ramping down */
    TEST_ASSERT_EQUAL_UINT32(1100, motion_now().emitted);
}

/* is_running() answers the same question without collecting anything, which is
   what lets a supervisor watch a run it does not own. */
static void test_asking_whether_it_runs_collects_nothing(void)
{
    setup_ready(CFG_GCONF);
    const tmc2209_move_t m = a_move(true, 1000);
    bool running = true;

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_is_running(&g_dev, &running));
    TEST_ASSERT_TRUE(running);

    gen_finish(1000);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_is_running(&g_dev, &running));
    TEST_ASSERT_FALSE(running);

    TEST_ASSERT_EQUAL(TMC2209_ERR_UNREAD, tmc2209_move(&g_dev, &m));
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
    TEST_ASSERT_FALSE(motion_now().running);
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

/* DIR belongs to the run while the run lasts. Flipping it between two pulses
   would have both halves counted in the direction the run started, and with no
   encoder that is not detected. ENN stays available throughout, because cutting
   the power stage is the one thing that must never be refused. */
static void test_dir_is_held_for_the_duration_of_a_run(void)
{
    setup_ready(CFG_GCONF);

    const tmc2209_move_t m = a_move(true, 4000);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));
    TEST_ASSERT_TRUE(g_board.level[TMC2209_LINE_DIR]);

    g_gen.emitted = 1000;
    TEST_ASSERT_EQUAL(TMC2209_ERR_BUSY,
                      tmc2209_line_write(&g_dev, TMC2209_LINE_DIR, false));
    TEST_ASSERT_TRUE(g_board.level[TMC2209_LINE_DIR]);   /* refused, not applied */
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_enable(&g_dev, false));

    gen_finish(4000);
    TEST_ASSERT_EQUAL_UINT32(4000, collect_count());
    TEST_ASSERT_EQUAL(TMC2209_OK,
                      tmc2209_line_write(&g_dev, TMC2209_LINE_DIR, false));
    TEST_ASSERT_FALSE(g_board.level[TMC2209_LINE_DIR]);
}

/* The hold ends with the run and not with a call to tmc2209_poll_motion(): the
   pin is free as soon as the last pulse is out, whether anyone asked or not. */
static void test_dir_is_free_once_the_pulses_stop(void)
{
    setup_ready(CFG_GCONF);

    const tmc2209_move_t m = a_move(true, 4000);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_move(&g_dev, &m));
    gen_finish(4000);

    TEST_ASSERT_EQUAL(TMC2209_OK,
                      tmc2209_line_write(&g_dev, TMC2209_LINE_DIR, false));
    /* And the count it produced is still there to be collected. */
    TEST_ASSERT_EQUAL_UINT32(4000, collect_count());
}

/* Without a stepgen the pin is nobody's, so no run can be in flight to hold it. */
static void test_dir_is_free_on_a_device_without_a_stepgen(void)
{
    setup_ready(CFG_GCONF);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_attach_stepgen(&g_dev, NULL));

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_line_write(&g_dev, TMC2209_LINE_DIR, true));
    TEST_ASSERT_TRUE(g_board.level[TMC2209_LINE_DIR]);
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

static void test_a_backend_failure_yields_no_count(void)
{
    setup_ready(CFG_GCONF);
    tmc2209_motion_t motion;

    g_gen.fail_state = 1;
    TEST_ASSERT_EQUAL(TMC2209_ERR_IO, tmc2209_poll_motion(&g_dev, &motion));

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
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_poll_motion(&g_dev, NULL));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_halt(NULL, true));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_retarget(NULL, 1000));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_is_running(&g_dev, NULL));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_attach_stepgen(NULL, &g_stepgen));
}

/* Construction attaches nothing, so a device that never saw a stepgen has no
   run to report and owes no count. */
static void test_init_leaves_the_stepgen_detached(void)
{
    setup_ready(CFG_GCONF);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_init(&g_dev, 0));

    tmc2209_motion_t motion;
    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND, tmc2209_poll_motion(&g_dev, &motion));
    TEST_ASSERT_FALSE(g_dev.count_unread);
}

void run_stepgen_tests(void)
{
    RUN_TEST(test_a_device_without_a_stepgen_refuses_every_motion_call);
    RUN_TEST(test_attach_rejects_an_incomplete_backend);
    RUN_TEST(test_attach_rejects_a_backend_that_pulses_too_narrowly);
    RUN_TEST(test_attach_is_refused_while_a_run_is_in_flight);
    RUN_TEST(test_init_leaves_the_stepgen_detached);

    RUN_TEST(test_dir_is_set_before_the_first_pulse);
    RUN_TEST(test_the_dir_level_reaches_the_pin_uninterpreted);
    RUN_TEST(test_a_move_that_misreads_the_shaft_bit_is_refused);
    RUN_TEST(test_a_move_that_declares_the_shaft_bit_correctly_runs);
    RUN_TEST(test_an_unknown_gconf_stops_the_move);

    RUN_TEST(test_a_finished_run_reports_its_count);
    RUN_TEST(test_polling_a_finished_run_reports_the_same_count);
    RUN_TEST(test_a_run_in_flight_shows_its_progress);
    RUN_TEST(test_a_move_needs_the_last_count_collected);
    RUN_TEST(test_polling_mid_run_does_not_pay_the_debt);
    RUN_TEST(test_a_first_move_owes_no_count);
    RUN_TEST(test_an_aborted_run_keeps_the_pulses_it_did_emit);
    RUN_TEST(test_a_ramped_halt_is_not_over_until_the_pulses_stop);
    RUN_TEST(test_asking_whether_it_runs_collects_nothing);

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
    RUN_TEST(test_dir_is_held_for_the_duration_of_a_run);
    RUN_TEST(test_dir_is_free_once_the_pulses_stop);
    RUN_TEST(test_dir_is_free_on_a_device_without_a_stepgen);

    RUN_TEST(test_a_refused_run_leaves_nothing_in_flight);
    RUN_TEST(test_a_backend_failure_yields_no_count);
    RUN_TEST(test_null_arguments_are_bad_arguments);
}
