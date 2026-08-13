/*
 * test_ramp.c: the ramp, run on the host with the pulses counted.
 *
 * A backend cannot be asked on hardware whether it emitted one pulse too many,
 * or whether it braked a thousand pulses late: both look like a motor that
 * arrived somewhere near where it was sent. Here the chunks are summed and the
 * question has an answer.
 */

#include "ramp.h"
#include "unity.h"

#define RESOLUTION_HZ 1000000U
#define MIN_PERIOD    2U
#define DURATION_MAX  32767U

/* What a run adds up to, chunk by chunk, as the encoder would take it. */
typedef struct {
    uint32_t pulses;
    uint64_t ticks;
    uint32_t peak_pps;
    uint32_t final_pps;
    uint32_t chunks;
    bool     ended;
} tally;

static tally drain(ramp_t *r, uint32_t target_pps, uint32_t budget, uint32_t limit)
{
    tally t = { 0 };

    while (t.pulses < limit) {
        ramp_chunk_t c;
        ramp_next(r, t.pulses, budget, target_pps, false, &c);

        for (uint32_t i = 0; i < c.count; i++) {
            t.ticks += ramp_period(r, &c);
        }

        t.pulses += c.count;
        t.chunks++;
        t.final_pps = c.rate_pps;
        if (c.rate_pps > t.peak_pps) {
            t.peak_pps = c.rate_pps;
        }

        if (r->pulses != 0U && t.pulses >= r->pulses) {
            t.ended = true;
            break;
        }
    }

    return t;
}

static void begin(ramp_t *r, uint32_t pulses, uint32_t pullin, uint32_t accel)
{
    const ramp_plan_t plan = {
        .pulses           = pulses,
        .pullin_pps       = pullin,
        .accel_pps_s      = accel,
        .resolution_hz    = RESOLUTION_HZ,
        .min_period_ticks = MIN_PERIOD,
    };
    ramp_begin(r, &plan);
}

/* ── Counts ─────────────────────────────────────────────────────────────── */

static void test_bounded_run_emits_exactly_its_pulses(void)
{
    ramp_t r;
    begin(&r, 5000U, 1000U, 20000U);

    const tally t = drain(&r, 40000U, 24U, 100000U);

    TEST_ASSERT_TRUE(t.ended);
    TEST_ASSERT_EQUAL_UINT32(5000U, t.pulses);
}

static void test_a_chunk_never_outruns_the_budget(void)
{
    ramp_t r;
    begin(&r, 5000U, 1000U, 20000U);

    uint32_t index = 0;
    while (index < 5000U) {
        ramp_chunk_t c;
        ramp_next(&r, index, 24U, 40000U, false, &c);
        TEST_ASSERT_GREATER_THAN_UINT32(0U, c.count);
        TEST_ASSERT_LESS_OR_EQUAL_UINT32(24U, c.count);
        index += c.count;
    }
}

/* ── The ramp ───────────────────────────────────────────────────────────── */

static void test_a_run_starts_and_ends_at_pullin(void)
{
    ramp_t r;
    begin(&r, 5000U, 1000U, 20000U);

    ramp_chunk_t first;
    ramp_next(&r, 0U, 24U, 40000U, false, &first);
    /* Sampled mid-chunk, so the first rate is just above pull-in, never below. */
    TEST_ASSERT_GREATER_OR_EQUAL_UINT32(1000U, first.rate_pps);
    TEST_ASSERT_LESS_THAN_UINT32(1100U, first.rate_pps);

    begin(&r, 5000U, 1000U, 20000U);
    const tally t = drain(&r, 40000U, 24U, 100000U);
    TEST_ASSERT_UINT32_WITHIN(50U, 1000U, t.final_pps);
}

static void test_a_long_run_reaches_cruise_and_holds_it(void)
{
    ramp_t r;
    begin(&r, 400000U, 1000U, 20000U);

    const tally t = drain(&r, 40000U, 24U, 500000U);

    TEST_ASSERT_UINT32_WITHIN(200U, 40000U, t.peak_pps);
}

static void test_a_short_run_is_a_triangle(void)
{
    /* 400 pulses at 20000 pps/s cannot reach 40000 pps: the ramp alone wants
       (40000² - 1000²) / 40000 = 39975 pulses, so this brakes almost at once. */
    ramp_t r;
    begin(&r, 400U, 1000U, 20000U);

    const tally t = drain(&r, 40000U, 24U, 10000U);

    TEST_ASSERT_EQUAL_UINT32(400U, t.pulses);
    TEST_ASSERT_LESS_THAN_UINT32(40000U, t.peak_pps);
    TEST_ASSERT_UINT32_WITHIN(100U, 1000U, t.final_pps);
}

static void test_the_ramp_takes_the_time_the_physics_says(void)
{
    /* 1000 to 40000 pps at 20000 pps/s is (40000 - 1000) / 20000 = 1.95 s up and
       the same down. Each ramp spends (40000² - 1000²) / (2 · 20000) = 39975
       pulses, and the 320050 left over are cruise, at 8.00125 s. */
    ramp_t r;
    begin(&r, 400000U, 1000U, 20000U);

    const tally t = drain(&r, 40000U, 24U, 500000U);

    const uint64_t expected_us = (2U * 1950000U) + 8001250U;

    TEST_ASSERT_EQUAL_UINT32(400000U, t.pulses);
    TEST_ASSERT_UINT64_WITHIN(expected_us / 50U, expected_us, t.ticks);
}

/* ── No ramp at all ─────────────────────────────────────────────────────── */

/* Both halves of a symbol carry a 15-bit duration field, and a period split
   evenly has to leave each half inside it at the slowest rate the backend
   allows: 1e6 / (2 * 32767), rounded up, is 16 pps. */
static void test_a_period_splits_into_two_encodable_halves(void)
{
    ramp_t r;
    begin(&r, 2000U, 16U, 0U);

    const tally t = drain(&r, 16U, 24U, 4000U);
    TEST_ASSERT_EQUAL_UINT32(2000U, t.pulses);

    begin(&r, 2000U, 16U, 0U);
    for (uint32_t index = 0; index < 2000U;) {
        ramp_chunk_t c;
        ramp_next(&r, index, 24U, 16U, false, &c);
        for (uint32_t i = 0; i < c.count; i++) {
            const uint32_t period = ramp_period(&r, &c);
            const uint32_t high   = period / 2U;
            TEST_ASSERT_GREATER_OR_EQUAL_UINT32(MIN_PERIOD, period);
            TEST_ASSERT_GREATER_THAN_UINT32(0U, high);
            TEST_ASSERT_LESS_OR_EQUAL_UINT32(DURATION_MAX, high);
            TEST_ASSERT_LESS_OR_EQUAL_UINT32(DURATION_MAX, period - high);
        }
        index += c.count;
    }
}

static void test_a_flat_run_holds_one_period(void)
{
    ramp_t r;
    begin(&r, 1000U, 8000U, 0U);

    const tally t = drain(&r, 8000U, 24U, 10000U);

    TEST_ASSERT_EQUAL_UINT32(1000U, t.pulses);
    TEST_ASSERT_EQUAL_UINT32(8000U, t.peak_pps);
    /* 1000 pulses at 8000 pps is an eighth of a second, to the tick. */
    TEST_ASSERT_UINT64_WITHIN(2U, 125000U, t.ticks);
}

static void test_the_carried_remainder_keeps_the_mean_rate(void)
{
    /* 90000 pps is 11.111 ticks: rounding down would run 1% fast, forever. */
    ramp_t r;
    begin(&r, 90000U, 90000U, 0U);

    const tally t = drain(&r, 90000U, 24U, 200000U);

    TEST_ASSERT_EQUAL_UINT32(90000U, t.pulses);
    TEST_ASSERT_UINT64_WITHIN(50U, RESOLUTION_HZ, t.ticks);
}

/* ── Halting ────────────────────────────────────────────────────────────── */

static void test_a_graceful_halt_brakes_to_pullin_and_ends(void)
{
    ramp_t r;
    begin(&r, 0U, 1000U, 20000U);

    /* Up to speed first, on a run with no end of its own. */
    uint32_t index = 0;
    for (int i = 0; i < 400; i++) {
        ramp_chunk_t c;
        ramp_next(&r, index, 24U, 40000U, false, &c);
        index += c.count;
    }

    uint32_t     last_rate = 0;
    ramp_chunk_t c         = { 0 };
    for (int i = 0; i < 100000 && !c.last; i++) {
        ramp_next(&r, index, 24U, 40000U, true, &c);
        TEST_ASSERT_LESS_OR_EQUAL_UINT32(last_rate == 0U ? 60000U : last_rate, c.rate_pps);
        last_rate = c.rate_pps;
        index += c.count;
    }

    TEST_ASSERT_TRUE(c.last);
    TEST_ASSERT_UINT32_WITHIN(50U, 1000U, c.rate_pps);
}

static void test_a_halt_at_pullin_ends_at_once(void)
{
    ramp_t r;
    begin(&r, 0U, 1000U, 20000U);

    ramp_chunk_t c;
    ramp_next(&r, 0U, 24U, 1000U, true, &c);

    TEST_ASSERT_TRUE(c.last);
    TEST_ASSERT_EQUAL_UINT32(1U, c.count);
}

/* ── Retargeting ────────────────────────────────────────────────────────── */

static void test_a_lowered_target_is_ramped_down_to(void)
{
    ramp_t r;
    begin(&r, 0U, 1000U, 20000U);

    uint32_t index = 0;
    for (int i = 0; i < 400; i++) {
        ramp_chunk_t c;
        ramp_next(&r, index, 24U, 40000U, false, &c);
        index += c.count;
    }

    ramp_chunk_t c = { 0 };
    for (int i = 0; i < 100000; i++) {
        ramp_next(&r, index, 24U, 5000U, false, &c);
        index += c.count;
    }

    TEST_ASSERT_UINT32_WITHIN(100U, 5000U, c.rate_pps);
}

static void test_a_target_under_pullin_is_held_at_pullin(void)
{
    ramp_t r;
    begin(&r, 0U, 4000U, 20000U);

    ramp_chunk_t c;
    for (int i = 0; i < 1000; i++) {
        ramp_next(&r, 0U, 24U, 500U, false, &c);
    }

    TEST_ASSERT_EQUAL_UINT32(4000U, c.rate_pps);
}

void run_ramp_tests(void)
{
    RUN_TEST(test_bounded_run_emits_exactly_its_pulses);
    RUN_TEST(test_a_chunk_never_outruns_the_budget);
    RUN_TEST(test_a_run_starts_and_ends_at_pullin);
    RUN_TEST(test_a_long_run_reaches_cruise_and_holds_it);
    RUN_TEST(test_a_short_run_is_a_triangle);
    RUN_TEST(test_the_ramp_takes_the_time_the_physics_says);
    RUN_TEST(test_a_period_splits_into_two_encodable_halves);
    RUN_TEST(test_a_flat_run_holds_one_period);
    RUN_TEST(test_the_carried_remainder_keeps_the_mean_rate);
    RUN_TEST(test_a_graceful_halt_brakes_to_pullin_and_ends);
    RUN_TEST(test_a_halt_at_pullin_ends_at_once);
    RUN_TEST(test_a_lowered_target_is_ramped_down_to);
    RUN_TEST(test_a_target_under_pullin_is_held_at_pullin);
}
