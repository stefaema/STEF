/*
 * test_lines.c: the control lines, against a fake board.
 *
 * A line call does what it says or refuses, and no other pin moves. The wiring
 * mask tells a board that does not connect DIAG from one that connects it and
 * reads low.
 *
 * ENN is active low, so enable() and the raw level disagree, and the tests ask
 * both to catch an inverted implementation.
 */

#include "tmc2209.h"
#include "unity.h"

#include <string.h>

/* A board with four pins. Levels persist, so a write reads back like a real
   output. */
typedef struct {
    bool     level[TMC2209_LINE_COUNT];
    unsigned writes[TMC2209_LINE_COUNT];
    unsigned reads[TMC2209_LINE_COUNT];
    int      fail_read;    /* backend failure, until cleared */
    int      fail_write;
} fake_board_t;

static fake_board_t    g_board;
static tmc2209_lines_t g_lines;
static tmc2209_t       g_dev;

static int board_read(void *ctx, tmc2209_line_t line)
{
    fake_board_t *b = (fake_board_t *)ctx;
    b->reads[line]++;
    if (b->fail_read) {
        return -1;
    }
    return (int)b->level[line];
}

static int board_write(void *ctx, tmc2209_line_t line, bool level)
{
    fake_board_t *b = (fake_board_t *)ctx;
    b->writes[line]++;
    if (b->fail_write) {
        return -1;
    }
    b->level[line] = level;
    return 0;
}

/* No bus is attached anywhere in this file, since lines and bytes are
   independent backends.
   @p wired is what this board connects, so a test can build a board missing a
   line and assert the refusal. */
static void setup_board(uint8_t wired)
{
    memset(&g_board, 0, sizeof g_board);

    g_lines.read  = board_read;
    g_lines.write = board_write;
    g_lines.ctx   = &g_board;
    g_lines.wired = wired;

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_init(&g_dev, 0));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_attach_lines(&g_dev, &g_lines));
}

static bool line_level(tmc2209_line_t line)
{
    bool level = false;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_line_read(&g_dev, line, &level));
    return level;
}

/* ── Attachment ─────────────────────────────────────────────────────────── */

/* A configuration-only caller attaches no lines and still gets a sensible
   answer. */
static void test_a_device_without_lines_refuses_every_line_call(void)
{
    setup_board(TMC2209_LINES_ALL);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_attach_lines(&g_dev, NULL));

    bool level = false;
    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND, tmc2209_line_read(&g_dev, TMC2209_LINE_DIAG, &level));
    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND, tmc2209_line_write(&g_dev, TMC2209_LINE_ENN, true));
    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND, tmc2209_enable(&g_dev, true));
    TEST_ASSERT_FALSE(tmc2209_line_is_wired(&g_dev, TMC2209_LINE_ENN));
}

/* Two different refusals: attach a backend, or the pin is not on this board.
   Separate codes let a bring-up routine tell a setup mistake from the
   wiring. */
static void test_a_missing_backend_reads_apart_from_a_missing_pin(void)
{
    setup_board(TMC2209_LINES_ALL & (uint8_t)~TMC2209_LINE_BIT(TMC2209_LINE_DIAG));
    TEST_ASSERT_EQUAL(TMC2209_ERR_UNWIRED, tmc2209_line_write(&g_dev, TMC2209_LINE_DIAG, true));

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_attach_lines(&g_dev, NULL));
    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND, tmc2209_line_write(&g_dev, TMC2209_LINE_DIAG, true));
}

/* ── Raw levels ─────────────────────────────────────────────────────────── */

static void test_a_written_level_reads_back(void)
{
    setup_board(TMC2209_LINES_ALL);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_line_write(&g_dev, TMC2209_LINE_DIR, true));
    TEST_ASSERT_TRUE(line_level(TMC2209_LINE_DIR));

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_line_write(&g_dev, TMC2209_LINE_DIR, false));
    TEST_ASSERT_FALSE(line_level(TMC2209_LINE_DIR));
}

/* The raw tier applies no polarity. */
static void test_a_raw_write_applies_no_polarity(void)
{
    setup_board(TMC2209_LINES_ALL);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_line_write(&g_dev, TMC2209_LINE_ENN, true));
    TEST_ASSERT_TRUE(g_board.level[TMC2209_LINE_ENN]);
}

static void test_each_line_moves_only_its_own_pin(void)
{
    setup_board(TMC2209_LINES_ALL);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_line_write(&g_dev, TMC2209_LINE_STEP, true));

    TEST_ASSERT_EQUAL(1U, g_board.writes[TMC2209_LINE_STEP]);
    TEST_ASSERT_EQUAL(0U, g_board.writes[TMC2209_LINE_ENN]);
    TEST_ASSERT_EQUAL(0U, g_board.writes[TMC2209_LINE_DIR]);
    TEST_ASSERT_EQUAL(0U, g_board.writes[TMC2209_LINE_DIAG]);
}

static void test_diag_reads(void)
{
    setup_board(TMC2209_LINES_ALL);

    g_board.level[TMC2209_LINE_DIAG] = true;
    TEST_ASSERT_TRUE(line_level(TMC2209_LINE_DIAG));
}

/* Driving an input is a caller error, so it is refused even on a board that
   wires everything. */
static void test_driving_an_input_is_refused(void)
{
    setup_board(TMC2209_LINES_ALL);

    TEST_ASSERT_EQUAL(TMC2209_ERR_ACCESS, tmc2209_line_write(&g_dev, TMC2209_LINE_DIAG, true));
    TEST_ASSERT_EQUAL(0U, g_board.writes[TMC2209_LINE_DIAG]);
}

/* An unwired line is refused before the access policy is checked, since it
   is the more specific answer. */
static void test_an_unwired_line_is_reported_as_unwired(void)
{
    setup_board(TMC2209_LINES_ALL & (uint8_t)~TMC2209_LINE_BIT(TMC2209_LINE_DIAG));

    bool level = false;
    TEST_ASSERT_FALSE(tmc2209_line_is_wired(&g_dev, TMC2209_LINE_DIAG));
    TEST_ASSERT_EQUAL(TMC2209_ERR_UNWIRED, tmc2209_line_read(&g_dev, TMC2209_LINE_DIAG, &level));
    TEST_ASSERT_EQUAL(TMC2209_ERR_UNWIRED, tmc2209_line_write(&g_dev, TMC2209_LINE_DIAG, true));
    TEST_ASSERT_EQUAL(0U, g_board.reads[TMC2209_LINE_DIAG]);
}

/* Missing one line leaves the rest usable, so the mask is per line. */
static void test_the_lines_a_board_does_wire_still_work(void)
{
    setup_board(TMC2209_LINES_ALL & (uint8_t)~TMC2209_LINE_BIT(TMC2209_LINE_DIAG));

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_enable(&g_dev, true));
    TEST_ASSERT_TRUE(tmc2209_line_is_wired(&g_dev, TMC2209_LINE_STEP));
}

/* A backend failure leaves the caller's variable untouched. */
static void test_a_backend_failure_yields_no_level(void)
{
    setup_board(TMC2209_LINES_ALL);
    g_board.fail_read = 1;

    bool level = true;
    TEST_ASSERT_EQUAL(TMC2209_ERR_IO, tmc2209_line_read(&g_dev, TMC2209_LINE_DIAG, &level));
    TEST_ASSERT_TRUE(level);

    g_board.fail_read  = 0;
    g_board.fail_write = 1;
    TEST_ASSERT_EQUAL(TMC2209_ERR_IO, tmc2209_line_write(&g_dev, TMC2209_LINE_DIR, true));
    TEST_ASSERT_EQUAL(TMC2209_ERR_IO, tmc2209_enable(&g_dev, true));
}

/* ── Enable ─────────────────────────────────────────────────────────────── */

/* The one place polarity is applied. Enabled is ENN low, and checking the
   level catches an inverted implementation that is self-consistent. */
static void test_enable_drives_enn_low(void)
{
    setup_board(TMC2209_LINES_ALL);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_enable(&g_dev, true));
    TEST_ASSERT_FALSE(g_board.level[TMC2209_LINE_ENN]);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_enable(&g_dev, false));
    TEST_ASSERT_TRUE(g_board.level[TMC2209_LINE_ENN]);
}

static void test_is_enabled_inverts_the_level_back(void)
{
    setup_board(TMC2209_LINES_ALL);

    bool on                         = false;
    g_board.level[TMC2209_LINE_ENN] = false;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_is_enabled(&g_dev, &on));
    TEST_ASSERT_TRUE(on);

    g_board.level[TMC2209_LINE_ENN] = true;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_is_enabled(&g_dev, &on));
    TEST_ASSERT_FALSE(on);
}

/* Enable is a pin and nothing else. A driver whose configuration would make it
   hold no current still enables, and polling is how the caller finds out. */
static void test_enable_touches_no_register(void)
{
    setup_board(TMC2209_LINES_ALL);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_enable(&g_dev, true));
    TEST_ASSERT_EQUAL(0U, g_dev.valid);
    TEST_ASSERT_EQUAL(1U, g_board.writes[TMC2209_LINE_ENN]);
}

void run_lines_tests(void)
{
    RUN_TEST(test_a_device_without_lines_refuses_every_line_call);
    RUN_TEST(test_a_missing_backend_reads_apart_from_a_missing_pin);

    RUN_TEST(test_a_written_level_reads_back);
    RUN_TEST(test_a_raw_write_applies_no_polarity);
    RUN_TEST(test_each_line_moves_only_its_own_pin);
    RUN_TEST(test_diag_reads);
    RUN_TEST(test_driving_an_input_is_refused);
    RUN_TEST(test_an_unwired_line_is_reported_as_unwired);
    RUN_TEST(test_the_lines_a_board_does_wire_still_work);
    RUN_TEST(test_a_backend_failure_yields_no_level);

    RUN_TEST(test_enable_drives_enn_low);
    RUN_TEST(test_is_enabled_inverts_the_level_back);
    RUN_TEST(test_enable_touches_no_register);
}
