/*
 * test_device.c — the transaction and shadow layer, against the mock device.
 *
 * The theme running through these is that the library must never quietly
 * present a belief it cannot justify. A write it could not confirm, a driver
 * that reset underneath it, a passthrough datagram it did not build: each one
 * has to end with the shadow refusing to answer rather than answering wrong.
 */

#include "unity.h"
#include "mock_tmc2209.h"

static mock_dev_t     g_mock;
static tmc2209_port_t g_port;
static tmc2209_bus_t  g_bus;
static tmc2209_t      g_dev;

static void setup_bus(uint8_t addr, bool echoes, uint8_t retries)
{
    mock_init(&g_mock, &g_port, addr, echoes);
    g_bus.port       = &g_port;
    g_bus.timeout_ms = 10;
    g_bus.retries    = retries;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_init(&g_dev, &g_bus, addr));
}

static void setup_ready(void)
{
    setup_bus(0, true, 1);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_begin(&g_dev, NULL));
}

/* ── Construction ───────────────────────────────────────────────────────── */

static void test_init_seeds_shadow_with_reset_values(void)
{
    setup_bus(0, true, 0);
    TEST_ASSERT_EQUAL_HEX32(0x10000053u, g_dev.shadow[tmc2209_reg_slot(TMC2209_CHOPCONF)]);
    TEST_ASSERT_EQUAL_HEX32(0x00071703u, g_dev.shadow[tmc2209_reg_slot(TMC2209_IHOLD_IRUN)]);
    TEST_ASSERT_EQUAL_UINT32(0, g_dev.dirty);
}

/* Nothing has been imposed on the device yet, so we have no grounds to claim
   we know what it holds. */
static void test_init_starts_untrusted(void)
{
    setup_bus(0, true, 0);
    TEST_ASSERT_FALSE(tmc2209_trusted(&g_dev));

    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_STALE, tmc2209_shadow(&g_dev, TMC2209_CHOPCONF, &v));
}

static void test_init_rejects_out_of_range_address(void)
{
    mock_init(&g_mock, &g_port, 0, true);
    g_bus.port = &g_port;
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_init(&g_dev, &g_bus, 4));
}

/* ── Access enforcement ─────────────────────────────────────────────────── */

/* The defect the Python library shipped: pull_motion() read five registers
   that the silicon has no read path for. */
static void test_reading_a_write_only_register_is_refused(void)
{
    setup_ready();
    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_ACCESS, tmc2209_read(&g_dev, TMC2209_IHOLD_IRUN, &v));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ACCESS, tmc2209_read(&g_dev, TMC2209_VACTUAL, &v));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ACCESS, tmc2209_read(&g_dev, TMC2209_SLAVECONF, &v));
}

static void test_refused_read_does_not_touch_the_bus(void)
{
    setup_ready();
    size_t before = g_mock.tx_len;
    uint32_t v = 0;
    (void)tmc2209_read(&g_dev, TMC2209_COOLCONF, &v);
    TEST_ASSERT_EQUAL_size_t(before, g_mock.tx_len);
}

static void test_writing_factory_conf_is_refused(void)
{
    setup_ready();
    TEST_ASSERT_EQUAL(TMC2209_ERR_ACCESS, tmc2209_write(&g_dev, TMC2209_FACTORY_CONF, 0));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ACCESS, tmc2209_stage(&g_dev, TMC2209_FACTORY_CONF, 0));
}

static void test_writing_a_read_only_register_is_refused(void)
{
    setup_ready();
    TEST_ASSERT_EQUAL(TMC2209_ERR_ACCESS, tmc2209_write(&g_dev, TMC2209_DRV_STATUS, 0));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ACCESS, tmc2209_write(&g_dev, TMC2209_TSTEP, 0));
}

static void test_unknown_register_is_rejected(void)
{
    setup_ready();
    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_read(&g_dev, (tmc2209_reg_t)0x04, &v));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_write(&g_dev, (tmc2209_reg_t)0x04, 0));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_read(&g_dev, (tmc2209_reg_t)0x33, &v));
}

/* The point of separating capability from policy: the diagnostic registers
   are reachable by an ordinary read, so raw RPC needs no special case and the
   PC tool never has to hand-assemble a passthrough datagram. */
static void test_diagnostic_registers_are_reachable_by_read(void)
{
    setup_ready();
    mock_set_reg(&g_mock, TMC2209_MSCURACT, 0x00FFu | (0x101u << 16));

    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_read(&g_dev, TMC2209_MSCURACT, &v));

    tmc2209_mscuract_t m = tmc2209_mscuract_decode(v);
    TEST_ASSERT_EQUAL_INT16(255,  m.cur_a);
    TEST_ASSERT_EQUAL_INT16(-255, m.cur_b);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_read(&g_dev, TMC2209_PWM_SCALE, &v));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_read(&g_dev, TMC2209_PWM_AUTO, &v));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_read(&g_dev, TMC2209_PWMCONF, &v));
}

static void test_diagnostic_registers_reject_writes(void)
{
    setup_ready();
    TEST_ASSERT_EQUAL(TMC2209_ERR_ACCESS, tmc2209_write(&g_dev, TMC2209_PWMCONF, 0));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ACCESS, tmc2209_write(&g_dev, TMC2209_MSCURACT, 0));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ACCESS, tmc2209_stage(&g_dev, TMC2209_PWMCONF, 0));
}

/* Adding readable registers must not enlarge what reflush imposes, or
   bring-up would start writing registers we deliberately never configure. */
static void test_reflush_ignores_the_diagnostic_registers(void)
{
    setup_ready();
    mock_set_reg(&g_mock, TMC2209_PWMCONF, 0xDEADBEEFu);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_reflush(&g_dev));
    TEST_ASSERT_EQUAL_HEX32(0xDEADBEEFu, mock_reg(&g_mock, TMC2209_PWMCONF));
}

/* ── Bring-up ───────────────────────────────────────────────────────────── */

static void test_begin_succeeds_and_imposes_config(void)
{
    setup_bus(0, true, 0);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_begin(&g_dev, NULL));
    TEST_ASSERT_TRUE(tmc2209_trusted(&g_dev));
    TEST_ASSERT_EQUAL_UINT32(0, g_dev.dirty);

    /* Every config register should now be on the device, not merely staged. */
    TEST_ASSERT_EQUAL_HEX32(0x00071703u, mock_reg(&g_mock, TMC2209_IHOLD_IRUN));
    TEST_ASSERT_EQUAL_HEX32(0x00000014u, mock_reg(&g_mock, TMC2209_TPOWERDOWN));
    TEST_ASSERT_EQUAL_HEX32(0x10000053u, mock_reg(&g_mock, TMC2209_CHOPCONF));
}

static void test_begin_clears_latched_gstat(void)
{
    setup_bus(0, true, 0);
    mock_set_reg(&g_mock, TMC2209_GSTAT, 0x1u);   /* power-on reset flag */
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_begin(&g_dev, NULL));
    TEST_ASSERT_EQUAL_HEX32(0x0u, mock_reg(&g_mock, TMC2209_GSTAT));
    TEST_ASSERT_TRUE(tmc2209_trusted(&g_dev));
}

/* Clearing GSTAT is what lets a later reset be recognised as recent, but it
   also destroys the only record of what the driver went through before we
   owned it. Bring-up therefore hands that record back on the way past. */
static void test_begin_reports_the_flags_it_clears(void)
{
    setup_bus(0, true, 0);
    mock_set_reg(&g_mock, TMC2209_GSTAT, 0x5u);   /* reset and uv_cp latched */

    tmc2209_gstat_t at_bringup = { 0 };
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_begin(&g_dev, &at_bringup));

    TEST_ASSERT_TRUE(at_bringup.reset);
    TEST_ASSERT_TRUE(at_bringup.uv_cp);
    TEST_ASSERT_FALSE(at_bringup.drv_err);
    TEST_ASSERT_EQUAL_HEX32(0x0u, mock_reg(&g_mock, TMC2209_GSTAT));
}

/* A caller with nothing to log must not have to invent a variable. */
static void test_begin_accepts_a_null_gstat_out(void)
{
    setup_bus(0, true, 0);
    mock_set_reg(&g_mock, TMC2209_GSTAT, 0x7u);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_begin(&g_dev, NULL));
    TEST_ASSERT_EQUAL_HEX32(0x0u, mock_reg(&g_mock, TMC2209_GSTAT));
}

/* Only the addressed driver may answer. This is what makes three drivers on
   one wire safe. */
static void test_begin_fails_when_addressed_driver_is_absent(void)
{
    mock_init(&g_mock, &g_port, 1, true);   /* mock answers to address 1 */
    g_bus.port       = &g_port;
    g_bus.timeout_ms = 10;
    g_bus.retries    = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_init(&g_dev, &g_bus, 0));   /* we ask address 0 */
    TEST_ASSERT_NOT_EQUAL(TMC2209_OK, tmc2209_begin(&g_dev, NULL));
}

static void test_addressing_reaches_the_right_driver(void)
{
    setup_bus(2, true, 0);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_begin(&g_dev, NULL));
    TEST_ASSERT_EQUAL_HEX8(2, g_mock.tx_log[1]);
}

/* ── Read and write ─────────────────────────────────────────────────────── */

static void test_read_returns_device_value(void)
{
    setup_ready();
    mock_set_reg(&g_mock, TMC2209_DRV_STATUS, 0x80170002u);

    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_read(&g_dev, TMC2209_DRV_STATUS, &v));
    TEST_ASSERT_EQUAL_HEX32(0x80170002u, v);
}

static void test_write_lands_on_the_device_and_updates_shadow(void)
{
    setup_ready();
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_write(&g_dev, TMC2209_IHOLD_IRUN, 0x00081F03u));
    TEST_ASSERT_EQUAL_HEX32(0x00081F03u, mock_reg(&g_mock, TMC2209_IHOLD_IRUN));

    /* A raw write keeps the shadow true rather than desyncing it, which is why
       RPC raw mode needs no special handling. */
    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_shadow(&g_dev, TMC2209_IHOLD_IRUN, &v));
    TEST_ASSERT_EQUAL_HEX32(0x00081F03u, v);
    TEST_ASSERT_TRUE(tmc2209_trusted(&g_dev));
}

/* A write datagram gets no reply, so IFCNT is the only acknowledgement. */
static void test_write_that_the_device_never_counted_is_reported(void)
{
    setup_bus(0, true, 0);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_begin(&g_dev, NULL));

    g_mock.freeze_ifcnt = 1;
    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_ACK, tmc2209_write(&g_dev, TMC2209_SGTHRS, 0x40u));
    TEST_ASSERT_FALSE(tmc2209_trusted(&g_dev));
}

static void test_read_of_readback_capable_register_adopts_device_value(void)
{
    setup_ready();
    mock_set_reg(&g_mock, TMC2209_GCONF, 0x000001C1u);

    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_read(&g_dev, TMC2209_GCONF, &v));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_shadow(&g_dev, TMC2209_GCONF, &v));
    TEST_ASSERT_EQUAL_HEX32(0x000001C1u, v);
}

/* ── Staging and flushing ───────────────────────────────────────────────── */

static void test_stage_does_no_io(void)
{
    setup_ready();
    size_t before = g_mock.tx_len;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_stage(&g_dev, TMC2209_SGTHRS, 0x50u));
    TEST_ASSERT_EQUAL_size_t(before, g_mock.tx_len);
    TEST_ASSERT_EQUAL_HEX32(0u, mock_reg(&g_mock, TMC2209_SGTHRS));
}

static void test_flush_writes_only_what_changed(void)
{
    setup_ready();
    unsigned before = g_mock.writes_seen;

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_stage(&g_dev, TMC2209_SGTHRS, 0x50u));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_stage(&g_dev, TMC2209_TCOOLTHRS, 0x123u));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_flush(&g_dev));

    TEST_ASSERT_EQUAL_UINT(2, g_mock.writes_seen - before);
    TEST_ASSERT_EQUAL_HEX32(0x50u,  mock_reg(&g_mock, TMC2209_SGTHRS));
    TEST_ASSERT_EQUAL_HEX32(0x123u, mock_reg(&g_mock, TMC2209_TCOOLTHRS));
    TEST_ASSERT_EQUAL_UINT32(0, g_dev.dirty);
}

static void test_flush_with_nothing_dirty_is_a_no_op(void)
{
    setup_ready();
    size_t before = g_mock.tx_len;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_flush(&g_dev));
    TEST_ASSERT_EQUAL_size_t(before, g_mock.tx_len);
}

/* One verification for the batch, not one per register: N writes plus a
   single IFCNT read. */
static void test_flush_verifies_the_batch_once(void)
{
    setup_ready();
    unsigned reads_before = g_mock.reads_seen;

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_stage(&g_dev, TMC2209_SGTHRS, 1));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_stage(&g_dev, TMC2209_TCOOLTHRS, 2));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_stage(&g_dev, TMC2209_TPWMTHRS, 3));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_flush(&g_dev));

    TEST_ASSERT_EQUAL_UINT(1, g_mock.reads_seen - reads_before);
}

static void test_flush_detects_a_lost_write_in_the_batch(void)
{
    setup_ready();
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_stage(&g_dev, TMC2209_SGTHRS, 1));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_stage(&g_dev, TMC2209_TCOOLTHRS, 2));
    g_mock.freeze_ifcnt = 1;

    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_ACK, tmc2209_flush(&g_dev));
    TEST_ASSERT_FALSE(tmc2209_trusted(&g_dev));
}

/* ── Trust ──────────────────────────────────────────────────────────────── */

/* GSTAT.reset means the driver browned out and lost its configuration, so
   everything the shadow claims is now fiction. */
static void test_gstat_reset_invalidates_the_shadow(void)
{
    setup_ready();
    TEST_ASSERT_TRUE(tmc2209_trusted(&g_dev));

    mock_set_reg(&g_mock, TMC2209_GSTAT, 0x1u);
    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_read(&g_dev, TMC2209_GSTAT, &v));
    TEST_ASSERT_FALSE(tmc2209_trusted(&g_dev));

    TEST_ASSERT_EQUAL(TMC2209_ERR_STALE, tmc2209_shadow(&g_dev, TMC2209_CHOPCONF, &v));
}

static void test_gstat_without_reset_leaves_trust_intact(void)
{
    setup_ready();
    mock_set_reg(&g_mock, TMC2209_GSTAT, 0x4u);   /* uv_cp only */
    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_read(&g_dev, TMC2209_GSTAT, &v));
    TEST_ASSERT_TRUE(tmc2209_trusted(&g_dev));
}

/* Eight registers are write-only, so the device cannot be interrogated back
   into agreement. Reflush imposes the shadow instead. */
static void test_reflush_restores_trust_by_imposing_the_shadow(void)
{
    setup_ready();
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_stage(&g_dev, TMC2209_IHOLD_IRUN, 0x00081F0Au));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_flush(&g_dev));

    /* The driver resets and loses everything. */
    mock_set_reg(&g_mock, TMC2209_IHOLD_IRUN, 0);
    tmc2209_invalidate(&g_dev);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_reflush(&g_dev));
    TEST_ASSERT_TRUE(tmc2209_trusted(&g_dev));
    TEST_ASSERT_EQUAL_HEX32(0x00081F0Au, mock_reg(&g_mock, TMC2209_IHOLD_IRUN));
}

static void test_reflush_does_not_write_gstat_or_factory_conf(void)
{
    setup_ready();
    mock_set_reg(&g_mock, TMC2209_GSTAT, 0x6u);
    mock_set_reg(&g_mock, TMC2209_FACTORY_CONF, 0x1Fu);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_reflush(&g_dev));

    /* Untouched: clearing flags is not restoring configuration, and the
       factory trim must never be overwritten. */
    TEST_ASSERT_EQUAL_HEX32(0x6u,  mock_reg(&g_mock, TMC2209_GSTAT));
    TEST_ASSERT_EQUAL_HEX32(0x1Fu, mock_reg(&g_mock, TMC2209_FACTORY_CONF));
}

/* ── Transport faults ───────────────────────────────────────────────────── */

static void test_crc_failure_recovers_on_retry(void)
{
    setup_bus(0, true, 2);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_begin(&g_dev, NULL));

    mock_set_reg(&g_mock, TMC2209_DRV_STATUS, 0xC0DEu);
    g_mock.fail_crc = 1;

    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_read(&g_dev, TMC2209_DRV_STATUS, &v));
    TEST_ASSERT_EQUAL_HEX32(0xC0DEu, v);
}

static void test_crc_failure_beyond_retries_is_reported(void)
{
    setup_bus(0, true, 1);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_begin(&g_dev, NULL));

    g_mock.fail_crc = 5;
    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_CRC, tmc2209_read(&g_dev, TMC2209_DRV_STATUS, &v));
}

/* A mismatched echo means something else drove the line while we were
   talking. It is the cheapest bus-collision detector we have. */
static void test_echo_mismatch_is_detected(void)
{
    setup_bus(0, true, 0);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_begin(&g_dev, NULL));

    g_mock.corrupt_echo = 1;
    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_ECHO, tmc2209_read(&g_dev, TMC2209_DRV_STATUS, &v));
}

static void test_silence_from_the_driver_times_out(void)
{
    setup_bus(0, true, 0);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_begin(&g_dev, NULL));

    g_mock.drop_reply = 1;
    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_TIMEOUT, tmc2209_read(&g_dev, TMC2209_DRV_STATUS, &v));
}

/* A reply for a register we did not ask about means a second driver answered.
   Retrying cannot fix that, so we must not burn the retry budget on it. */
static void test_wrong_register_reply_fails_without_retrying(void)
{
    setup_bus(0, true, 3);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_begin(&g_dev, NULL));

    unsigned before = g_mock.reads_seen;
    g_mock.wrong_reg = 1;
    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_REG, tmc2209_read(&g_dev, TMC2209_DRV_STATUS, &v));
    TEST_ASSERT_EQUAL_UINT(1, g_mock.reads_seen - before);
}

/* A full-duplex backend, such as the SIL simulator over USB, produces no
   echo. The library must not wait for one. */
static void test_non_echoing_port_works(void)
{
    setup_bus(0, false, 0);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_begin(&g_dev, NULL));
    TEST_ASSERT_TRUE(tmc2209_trusted(&g_dev));

    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_read(&g_dev, TMC2209_IOIN, &v));
    TEST_ASSERT_EQUAL_HEX8(TMC2209_IOIN_VERSION, tmc2209_ioin_decode(v).version);
}

/* ── Passthrough ────────────────────────────────────────────────────────── */

static void test_passthrough_moves_bytes_verbatim(void)
{
    setup_ready();
    mock_set_reg(&g_mock, TMC2209_MSCNT, 0x2A5u);

    uint8_t req[TMC2209_READ_REQ_LEN];
    tmc2209_frame_read_request(req, 0, TMC2209_MSCNT);

    uint8_t reply[TMC2209_REPLY_LEN] = { 0 };
    TEST_ASSERT_EQUAL(TMC2209_OK,
                      tmc2209_bus_xfer(&g_bus, req, sizeof req, reply, sizeof reply));

    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_frame_parse_reply(reply, TMC2209_MSCNT, &v));
    TEST_ASSERT_EQUAL_HEX32(0x2A5u, v);
}

/* Passthrough is the one path that can change driver state behind the
   shadow's back, because the bytes are deliberately uninterpretable. */
static void test_passthrough_write_desyncs_until_invalidated(void)
{
    setup_ready();

    uint8_t dg[TMC2209_WRITE_LEN];
    tmc2209_frame_write(dg, 0, TMC2209_IHOLD_IRUN, 0x000A0A0Au);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_bus_xfer(&g_bus, dg, sizeof dg, NULL, 0));

    /* The device moved; the shadow did not notice. */
    TEST_ASSERT_EQUAL_HEX32(0x000A0A0Au, mock_reg(&g_mock, TMC2209_IHOLD_IRUN));
    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_shadow(&g_dev, TMC2209_IHOLD_IRUN, &v));
    TEST_ASSERT_EQUAL_HEX32(0x00071703u, v);   /* stale, and it does not know */

    /* Which is exactly why the caller must say so, and reflush is the cure. */
    tmc2209_invalidate(&g_dev);
    TEST_ASSERT_EQUAL(TMC2209_ERR_STALE, tmc2209_shadow(&g_dev, TMC2209_IHOLD_IRUN, &v));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_reflush(&g_dev));
    TEST_ASSERT_EQUAL_HEX32(0x00071703u, mock_reg(&g_mock, TMC2209_IHOLD_IRUN));
}

static void test_passthrough_rejects_oversized_frames(void)
{
    setup_ready();
    uint8_t big[128] = { 0 };
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG,
                      tmc2209_bus_xfer(&g_bus, big, sizeof big, NULL, 0));
}

void run_device_tests(void)
{
    RUN_TEST(test_init_seeds_shadow_with_reset_values);
    RUN_TEST(test_init_starts_untrusted);
    RUN_TEST(test_init_rejects_out_of_range_address);

    RUN_TEST(test_reading_a_write_only_register_is_refused);
    RUN_TEST(test_refused_read_does_not_touch_the_bus);
    RUN_TEST(test_writing_factory_conf_is_refused);
    RUN_TEST(test_writing_a_read_only_register_is_refused);
    RUN_TEST(test_unknown_register_is_rejected);
    RUN_TEST(test_diagnostic_registers_are_reachable_by_read);
    RUN_TEST(test_diagnostic_registers_reject_writes);
    RUN_TEST(test_reflush_ignores_the_diagnostic_registers);

    RUN_TEST(test_begin_succeeds_and_imposes_config);
    RUN_TEST(test_begin_clears_latched_gstat);
    RUN_TEST(test_begin_reports_the_flags_it_clears);
    RUN_TEST(test_begin_accepts_a_null_gstat_out);
    RUN_TEST(test_begin_fails_when_addressed_driver_is_absent);
    RUN_TEST(test_addressing_reaches_the_right_driver);

    RUN_TEST(test_read_returns_device_value);
    RUN_TEST(test_write_lands_on_the_device_and_updates_shadow);
    RUN_TEST(test_write_that_the_device_never_counted_is_reported);
    RUN_TEST(test_read_of_readback_capable_register_adopts_device_value);

    RUN_TEST(test_stage_does_no_io);
    RUN_TEST(test_flush_writes_only_what_changed);
    RUN_TEST(test_flush_with_nothing_dirty_is_a_no_op);
    RUN_TEST(test_flush_verifies_the_batch_once);
    RUN_TEST(test_flush_detects_a_lost_write_in_the_batch);

    RUN_TEST(test_gstat_reset_invalidates_the_shadow);
    RUN_TEST(test_gstat_without_reset_leaves_trust_intact);
    RUN_TEST(test_reflush_restores_trust_by_imposing_the_shadow);
    RUN_TEST(test_reflush_does_not_write_gstat_or_factory_conf);

    RUN_TEST(test_crc_failure_recovers_on_retry);
    RUN_TEST(test_crc_failure_beyond_retries_is_reported);
    RUN_TEST(test_echo_mismatch_is_detected);
    RUN_TEST(test_silence_from_the_driver_times_out);
    RUN_TEST(test_wrong_register_reply_fails_without_retrying);
    RUN_TEST(test_non_echoing_port_works);

    RUN_TEST(test_passthrough_moves_bytes_verbatim);
    RUN_TEST(test_passthrough_write_desyncs_until_invalidated);
    RUN_TEST(test_passthrough_rejects_oversized_frames);
}
