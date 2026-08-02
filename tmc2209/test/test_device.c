/*
 * test_device.c: the transaction and cache layer, against the mock device.
 *
 * Two themes. The library must never present a value it cannot justify: a
 * write it could not confirm, a driver that reset underneath it, or a
 * passthrough datagram it did not build all have to end with the cache
 * refusing to answer. And it must never write a value nobody asked for, which
 * is the defect the old reset-value seeding shipped.
 */

#include "unity.h"
#include "mock_tmc2209.h"

#include <string.h>

static mock_dev_t     g_mock;
static tmc2209_uart_t g_uart;
static tmc2209_t      g_dev;

/* A complete configuration. GCONF carries pdn_disable and mstep_reg_select,
   without which the driver takes microstep resolution from the address straps
   and the UART pin keeps its standstill function. */
#define CFG_GCONF 0x000000C0U

static const tmc2209_regval_t k_config[] = {
    { TMC2209_GCONF,      CFG_GCONF    },
    { TMC2209_SLAVECONF,  0x00000200U  },
    { TMC2209_IHOLD_IRUN, 0x00081810U  },
    { TMC2209_TPOWERDOWN, 0x00000014U  },
    { TMC2209_TPWMTHRS,   0x000001F4U  },
    { TMC2209_TCOOLTHRS,  0x000003E8U  },
    { TMC2209_VACTUAL,    0x00000000U  },
    { TMC2209_SGTHRS,     0x00000050U  },
    { TMC2209_COOLCONF,   0x00010203U  },
    { TMC2209_CHOPCONF,   0x14010053U  },
};

static void setup_uart(uint8_t addr, bool echoes, uint8_t retries)
{
    mock_init(&g_mock, &g_uart, addr, echoes);
    g_uart.timeout_ms = 10;
    g_uart.retries    = retries;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_init(&g_dev, addr));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_attach_uart(&g_dev, &g_uart));
}

static void setup_ready(void)
{
    setup_uart(0, true, 1);
    TEST_ASSERT_EQUAL(TMC2209_OK,
        tmc2209_bringup(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));
}

static tmc2209_err_t write_one(tmc2209_reg_t reg, uint32_t value)
{
    const tmc2209_regval_t op = { reg, value };
    return tmc2209_write(&g_dev, &op, 1, NULL);
}

/* ── Construction ───────────────────────────────────────────────────────── */

/* No datasheet defaults are seeded, so there is nothing to read and nothing
   bringup() could write that the caller did not supply. */
static void test_init_leaves_every_slot_invalid(void)
{
    setup_uart(0, true, 0);
    TEST_ASSERT_EQUAL_UINT32(0, g_dev.valid);
    TEST_ASSERT_FALSE(tmc2209_all_owned_valid(&g_dev));

    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_INVALID_SLOT, tmc2209_read(&g_dev, TMC2209_CHOPCONF, &v));
    TEST_ASSERT_EQUAL(TMC2209_ERR_INVALID_SLOT, tmc2209_read(&g_dev, TMC2209_VACTUAL, &v));
}

/* Covers attach_uart too, since setup_uart() calls both. Attaching a backend is
   bookkeeping, and bookkeeping that talks to a driver cannot be undone. */
static void test_construction_does_no_io(void)
{
    setup_uart(0, true, 0);
    TEST_ASSERT_EQUAL_size_t(0, g_mock.tx_len);
}

static void test_init_rejects_out_of_range_address(void)
{
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_init(&g_dev, 4));
}

/* ── Uart attachment ────────────────────────────────────────────────────── */

/* Half a backend is not a backend: accepting one defers the crash to the first
   transaction rather than rejecting it at the seam. */
static void test_attach_uart_rejects_an_incomplete_backend(void)
{
    mock_init(&g_mock, &g_uart, 0, true);
    g_uart.timeout_ms = 10;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_init(&g_dev, 0));

    tmc2209_uart_t half = g_uart;

    half.tx = NULL;
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_attach_uart(&g_dev, &half));

    half = g_uart;
    half.rx = NULL;
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_attach_uart(&g_dev, &half));
}

/* A rejected backend leaves the previous one in place, so a device that was
   working keeps working rather than losing its wire to a bad argument. */
static void test_a_rejected_uart_does_not_displace_the_attached_one(void)
{
    setup_ready();

    tmc2209_uart_t half = g_uart;
    half.tx = NULL;
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_attach_uart(&g_dev, &half));

    TEST_ASSERT_EQUAL(TMC2209_OK, write_one(TMC2209_VACTUAL, 0x1234U));
    TEST_ASSERT_EQUAL_HEX32(0x1234U, mock_reg(&g_mock, TMC2209_VACTUAL));
}

/* Every call that would put a byte on the wire has to answer, not fault, on a
   device whose uart was never attached or was detached. */
static void test_a_device_without_a_uart_refuses_every_transaction(void)
{
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_init(&g_dev, 0));

    uint32_t v = 0;
    const tmc2209_regval_t op = { TMC2209_VACTUAL, 0 };
    tmc2209_ihold_irun_t   c  = { 0, 0, 0 };

    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND,
        tmc2209_bringup(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));
    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND, tmc2209_write(&g_dev, &op, 1, NULL));
    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND, tmc2209_poll_health(&g_dev, &v));
    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND, tmc2209_poll_raw(&g_dev, TMC2209_IOIN, &v));
    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND, tmc2209_poll_version(&g_dev, (uint8_t *)&v));
    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND, tmc2209_verify_config(&g_dev, &v));
    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND, tmc2209_clear_faults(&g_dev, TMC2209_DRIVER_RESET));
    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND, tmc2209_set_current(&g_dev, &c));
}

/* Detaching is how a wire is handed over, so it has to be reachable through the
   same call that attached it. */
static void test_detaching_the_uart_stops_transactions(void)
{
    setup_ready();
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_attach_uart(&g_dev, NULL));

    uint32_t conditions = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_BACKEND, tmc2209_poll_health(&g_dev, &conditions));
}

/* The cache is the device's, so it survives losing and regaining the wire. */
static void test_reattaching_a_uart_keeps_the_cache(void)
{
    setup_ready();
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_attach_uart(&g_dev, NULL));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_attach_uart(&g_dev, &g_uart));

    TEST_ASSERT_TRUE(tmc2209_all_owned_valid(&g_dev));

    uint32_t gconf = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_read(&g_dev, TMC2209_GCONF, &gconf));
    TEST_ASSERT_EQUAL_HEX32(CFG_GCONF, gconf);
}

/* One wire, up to four drivers. Each keeps its own cache and its own address. */
static void test_two_devices_share_one_uart(void)
{
    setup_uart(0, true, 0);

    tmc2209_t second;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_init(&second, 1));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_attach_uart(&second, &g_uart));

    TEST_ASSERT_EQUAL_PTR(g_dev.uart, second.uart);
    TEST_ASSERT_EQUAL_UINT8(0, g_dev.addr);
    TEST_ASSERT_EQUAL_UINT8(1, second.addr);

    TEST_ASSERT_EQUAL(TMC2209_OK,
        tmc2209_bringup(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));
    TEST_ASSERT_TRUE(tmc2209_all_owned_valid(&g_dev));
    TEST_ASSERT_FALSE(tmc2209_all_owned_valid(&second));
}

/* ── Bring-up ──────────────────────────────────────────────────────────────── */

static void test_bringup_writes_the_whole_configuration(void)
{
    setup_ready();
    for (size_t i = 0; i < TMC2209_NELEM(k_config); i++) {
        TEST_ASSERT_EQUAL_HEX32(k_config[i].value,
                                mock_reg(&g_mock, k_config[i].reg));
    }
    TEST_ASSERT_TRUE(tmc2209_all_owned_valid(&g_dev));
}

/* The old table seeded GCONF with its datasheet reset
   value and bringup() imposed the cache, so bringing up a fresh driver cleared
   mstep_reg_select and handed microstep resolution back to the address straps.
   The straps are the address on the wire, so all three motors would have run at
   different resolutions. */
static void test_bringup_never_writes_a_value_the_caller_did_not_supply(void)
{
    setup_ready();

    uint32_t gconf = mock_reg(&g_mock, TMC2209_GCONF);
    tmc2209_gconf_t g = tmc2209_gconf_decode(gconf);
    TEST_ASSERT_TRUE(g.mstep_reg_select);
    TEST_ASSERT_TRUE(g.pdn_disable);
    TEST_ASSERT_EQUAL_HEX32(CFG_GCONF, gconf);
}

/* There are no defaults to complete a partial configuration with, so a gap is
   refused rather than filled. */
static void test_bringup_rejects_a_configuration_with_a_gap(void)
{
    setup_uart(0, true, 1);
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG,
        tmc2209_bringup(&g_dev, k_config, TMC2209_NELEM(k_config) - 1, NULL));
    TEST_ASSERT_EQUAL_size_t(0, g_mock.tx_len);
}

static void test_bringup_rejects_a_register_it_does_not_own(void)
{
    const tmc2209_regval_t sneaky[] = {
        { TMC2209_GCONF,        CFG_GCONF },
        { TMC2209_FACTORY_CONF, 0         },   /* would detune the oscillator */
    };
    setup_uart(0, true, 1);
    TEST_ASSERT_EQUAL(TMC2209_ERR_ACCESS,
        tmc2209_bringup(&g_dev, sneaky, TMC2209_NELEM(sneaky), NULL));
    TEST_ASSERT_EQUAL_size_t(0, g_mock.tx_len);
}

/* VACTUAL is owned, so every configuration names it, and a non-zero value there
   spins the motor as the last datagram lands. Refused before anything goes out,
   which is what makes it a caught mistake rather than an observed one. */
static void test_bringup_refuses_a_configuration_that_asks_for_motion(void)
{
    tmc2209_regval_t moving[TMC2209_NELEM(k_config)];
    memcpy(moving, k_config, sizeof moving);
    for (size_t i = 0; i < TMC2209_NELEM(moving); i++) {
        if (moving[i].reg == TMC2209_VACTUAL) {
            moving[i].value = 0x000100U;
        }
    }

    setup_uart(0, true, 1);
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG,
        tmc2209_bringup(&g_dev, moving, TMC2209_NELEM(moving), NULL));
    TEST_ASSERT_EQUAL_size_t(0, g_mock.tx_len);
    TEST_ASSERT_FALSE(tmc2209_all_owned_valid(&g_dev));
}

/* Standing still is bring-up's business. Asking to move afterwards is the
   caller's, and nothing here narrows what set_velocity() accepts. */
static void test_velocity_is_free_to_move_after_bringup(void)
{
    setup_ready();
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_set_velocity(&g_dev, 0x000100));
    TEST_ASSERT_EQUAL_HEX32(0x000100U, mock_reg(&g_mock, TMC2209_VACTUAL));
}

/* The trim differs per part, so it is read off the driver rather than assumed.
   A seeded zero would be a value no real part ever holds. */
static void test_bringup_reads_constant_registers_off_the_part(void)
{
    setup_ready();

    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_read(&g_dev, TMC2209_FACTORY_CONF, &v));
    TEST_ASSERT_EQUAL_HEX32(MOCK_RESET_FACTORY_CONF, v);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_read(&g_dev, TMC2209_PWMCONF, &v));
    TEST_ASSERT_EQUAL_HEX32(MOCK_RESET_PWMCONF, v);
}

static void test_bringup_clears_latched_gstat(void)
{
    setup_uart(0, true, 1);
    mock_set_reg(&g_mock, TMC2209_GSTAT, 0x5U);   /* reset | uv_cp */

    TEST_ASSERT_EQUAL(TMC2209_OK,
        tmc2209_bringup(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));
    TEST_ASSERT_EQUAL_HEX32(0, mock_reg(&g_mock, TMC2209_GSTAT));
}

static void test_bringup_reports_the_flags_it_clears(void)
{
    setup_uart(0, true, 1);
    mock_set_reg(&g_mock, TMC2209_GSTAT, 0x5U);

    tmc2209_gstat_t at_bringup = { false };
    TEST_ASSERT_EQUAL(TMC2209_OK,
        tmc2209_bringup(&g_dev, k_config, TMC2209_NELEM(k_config), &at_bringup));

    TEST_ASSERT_TRUE(at_bringup.reset);
    TEST_ASSERT_FALSE(at_bringup.drv_err);
    TEST_ASSERT_TRUE(at_bringup.uv_cp);
}

static void test_bringup_fails_when_the_addressed_driver_is_absent(void)
{
    setup_uart(1, true, 0);            /* library talks to address 1 */
    g_mock.addr = 2;                  /* only address 2 answers */

    TEST_ASSERT_EQUAL(TMC2209_ERR_RX_TIMEOUT,
        tmc2209_bringup(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));
    TEST_ASSERT_FALSE(tmc2209_all_owned_valid(&g_dev));
}

static void test_addressing_reaches_the_right_driver(void)
{
    setup_uart(2, true, 1);
    TEST_ASSERT_EQUAL(TMC2209_OK,
        tmc2209_bringup(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));

    TEST_ASSERT_EQUAL_HEX8(2, g_mock.tx_log[1]);   /* slave address byte */
}

/* ── Cached reads ───────────────────────────────────────────────────────── */

static void test_read_answers_owned_registers_from_the_cache(void)
{
    setup_ready();
    size_t before = g_mock.tx_len;

    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_read(&g_dev, TMC2209_IHOLD_IRUN, &v));
    TEST_ASSERT_EQUAL_HEX32(0x00081810U, v);

    /* Write-only driver-side, so the cache is the only possible source, and no
       wire traffic may have happened. */
    TEST_ASSERT_EQUAL_size_t(before, g_mock.tx_len);
}

/* A remembered fault flag or load estimate describes a moment that has passed.
   Answering from the slot would report a healthy driver sitting in
   overtemperature. */
static void test_read_refuses_volatile_registers(void)
{
    setup_ready();
    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_ACCESS, tmc2209_read(&g_dev, TMC2209_DRV_STATUS, &v));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ACCESS, tmc2209_read(&g_dev, TMC2209_SG_RESULT, &v));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ACCESS, tmc2209_read(&g_dev, TMC2209_GSTAT, &v));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ACCESS, tmc2209_read(&g_dev, TMC2209_TSTEP, &v));
}

static void test_read_rejects_an_unknown_register(void)
{
    setup_ready();
    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_read(&g_dev, (tmc2209_reg_t)0x04, &v));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_read(&g_dev, (tmc2209_reg_t)0x33, &v));
}

static void test_read_refuses_an_invalidated_slot(void)
{
    setup_ready();
    tmc2209_invalidate_owned(&g_dev);

    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_INVALID_SLOT, tmc2209_read(&g_dev, TMC2209_VACTUAL, &v));

    /* A brownout does not change the factory trim, so constants survive. */
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_read(&g_dev, TMC2209_FACTORY_CONF, &v));
}

/* ── Batch writes ───────────────────────────────────────────────────────── */

static void test_write_lands_on_the_device_and_updates_the_cache(void)
{
    setup_ready();
    TEST_ASSERT_EQUAL(TMC2209_OK, write_one(TMC2209_SGTHRS, 0x42U));
    TEST_ASSERT_EQUAL_HEX32(0x42U, mock_reg(&g_mock, TMC2209_SGTHRS));

    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_read(&g_dev, TMC2209_SGTHRS, &v));
    TEST_ASSERT_EQUAL_HEX32(0x42U, v);
}

/* Three datagrams and one IFCNT read, rather than three of each. */
static void test_write_verifies_the_batch_once(void)
{
    setup_ready();
    unsigned reads_before = g_mock.reads_seen;

    const tmc2209_regval_t ops[] = {
        { TMC2209_SGTHRS,    0x11U },
        { TMC2209_TCOOLTHRS, 0x22U },
        { TMC2209_COOLCONF,  0x33U },
    };
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_write(&g_dev, ops, TMC2209_NELEM(ops), NULL));

    TEST_ASSERT_EQUAL_UINT(1, g_mock.reads_seen - reads_before);
    TEST_ASSERT_EQUAL_HEX32(0x11U, mock_reg(&g_mock, TMC2209_SGTHRS));
    TEST_ASSERT_EQUAL_HEX32(0x22U, mock_reg(&g_mock, TMC2209_TCOOLTHRS));
    TEST_ASSERT_EQUAL_HEX32(0x33U, mock_reg(&g_mock, TMC2209_COOLCONF));
}

/* An op whose value already matches a valid slot changes nothing, so it never
   reaches the wire. This is what recovers the old flush()'s saving without any
   staging state. */
static void test_write_skips_ops_that_change_nothing(void)
{
    setup_ready();
    unsigned writes_before = g_mock.writes_seen;

    TEST_ASSERT_EQUAL(TMC2209_OK,
        tmc2209_write(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));

    TEST_ASSERT_EQUAL_UINT(writes_before, g_mock.writes_seen);
    TEST_ASSERT_TRUE(tmc2209_all_owned_valid(&g_dev));
}

static void test_write_sends_only_the_op_that_changed(void)
{
    setup_ready();
    unsigned writes_before = g_mock.writes_seen;

    tmc2209_regval_t ops[TMC2209_NELEM(k_config)];
    memcpy(ops, k_config, sizeof k_config);
    ops[7].value = 0x7FU;   /* SGTHRS */

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_write(&g_dev, ops, TMC2209_NELEM(ops), NULL));
    TEST_ASSERT_EQUAL_UINT(1, g_mock.writes_seen - writes_before);
    TEST_ASSERT_EQUAL_HEX32(0x7FU, mock_reg(&g_mock, TMC2209_SGTHRS));
}

/* Last value wins, and the superseded op is dropped rather than transmitted. */
static void test_write_applies_the_last_value_for_a_repeated_register(void)
{
    setup_ready();
    unsigned writes_before = g_mock.writes_seen;

    const tmc2209_regval_t ops[] = {
        { TMC2209_SGTHRS, 0xAAU },
        { TMC2209_SGTHRS, 0xBBU },
    };
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_write(&g_dev, ops, TMC2209_NELEM(ops), NULL));

    TEST_ASSERT_EQUAL_UINT(1, g_mock.writes_seen - writes_before);
    TEST_ASSERT_EQUAL_HEX32(0xBBU, mock_reg(&g_mock, TMC2209_SGTHRS));
}

static void test_write_rejects_a_register_it_does_not_own(void)
{
    setup_ready();
    TEST_ASSERT_EQUAL(TMC2209_ERR_ACCESS, write_one(TMC2209_DRV_STATUS, 0));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ACCESS, write_one(TMC2209_FACTORY_CONF, 0));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ACCESS, write_one(TMC2209_GSTAT, 1));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG,    write_one((tmc2209_reg_t)0x04, 0));
}

/* Validation happens before any byte goes out, so a batch cannot be half sent
   and then rejected for an op it was never allowed to make. */
static void test_write_validates_the_whole_batch_before_sending(void)
{
    setup_ready();
    unsigned writes_before = g_mock.writes_seen;

    const tmc2209_regval_t ops[] = {
        { TMC2209_SGTHRS,     0x11U },
        { TMC2209_DRV_STATUS, 0x22U },   /* not writable */
    };
    TEST_ASSERT_EQUAL(TMC2209_ERR_ACCESS,
        tmc2209_write(&g_dev, ops, TMC2209_NELEM(ops), NULL));

    TEST_ASSERT_EQUAL_UINT(writes_before, g_mock.writes_seen);
}

static void test_write_rejects_an_empty_batch(void)
{
    setup_ready();
    const tmc2209_regval_t op = { TMC2209_SGTHRS, 0 };
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_write(&g_dev, &op, 0, NULL));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG, tmc2209_write(&g_dev, NULL, 1, NULL));
}

/* Nothing in a batch is confirmed until the IFCNT read at the end, so an op
   transmitted before the failure is no better known than one that never went
   out at all. */
static void test_a_failed_batch_invalidates_every_slot_in_it(void)
{
    setup_ready();

    const tmc2209_regval_t ops[] = {
        { TMC2209_SGTHRS,    0x11U },
        { TMC2209_TCOOLTHRS, 0x22U },
        { TMC2209_COOLCONF,  0x33U },
    };

    g_mock.corrupt_echo = 2;   /* both attempts at op 0 fail */
    size_t failed_at = 999;
    TEST_ASSERT_EQUAL(TMC2209_ERR_ECHO,
        tmc2209_write(&g_dev, ops, TMC2209_NELEM(ops), &failed_at));

    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_INVALID_SLOT, tmc2209_read(&g_dev, TMC2209_SGTHRS, &v));
    TEST_ASSERT_EQUAL(TMC2209_ERR_INVALID_SLOT, tmc2209_read(&g_dev, TMC2209_TCOOLTHRS, &v));
    TEST_ASSERT_EQUAL(TMC2209_ERR_INVALID_SLOT, tmc2209_read(&g_dev, TMC2209_COOLCONF, &v));
    TEST_ASSERT_FALSE(tmc2209_all_owned_valid(&g_dev));

    /* Diagnostic only: which op the library was on when it gave up. */
    TEST_ASSERT_EQUAL_size_t(0, failed_at);
}

/* The driver accepted the datagram but did not count it, so the write cannot be
   shown to have landed. */
static void test_a_write_the_device_never_counted_is_reported(void)
{
    setup_ready();
    g_mock.freeze_ifcnt = 1;

    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_ACK, write_one(TMC2209_SGTHRS, 0x55U));
    TEST_ASSERT_FALSE(tmc2209_all_owned_valid(&g_dev));

    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_INVALID_SLOT, tmc2209_read(&g_dev, TMC2209_SGTHRS, &v));
}

/* No single op is at fault when the batch counter does not add up. */
static void test_failed_at_is_n_when_the_batch_check_fails(void)
{
    setup_ready();
    const tmc2209_regval_t ops[] = {
        { TMC2209_SGTHRS,    0x11U },
        { TMC2209_TCOOLTHRS, 0x22U },
    };
    g_mock.freeze_ifcnt = 1;

    size_t failed_at = 999;
    TEST_ASSERT_EQUAL(TMC2209_ERR_NO_ACK,
        tmc2209_write(&g_dev, ops, TMC2209_NELEM(ops), &failed_at));
    TEST_ASSERT_EQUAL_size_t(TMC2209_NELEM(ops), failed_at);
}

/* ── Conditions ─────────────────────────────────────────────────────────── */

static void test_poll_health_is_clear_on_a_healthy_driver(void)
{
    setup_ready();
    uint32_t conditions = 0xFFFFU;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_poll_health(&g_dev, &conditions));
    TEST_ASSERT_EQUAL_HEX32(0, conditions);
}

/* One condition set from two registers: the caller never learns that brownout
   lives in GSTAT and overtemperature lives in DRV_STATUS. */
static void test_poll_health_merges_both_registers(void)
{
    setup_ready();
    mock_set_reg(&g_mock, TMC2209_GSTAT, 0x4U);                    /* uv_cp */
    mock_set_reg(&g_mock, TMC2209_DRV_STATUS, (1U << 1) | (1U << 4));  /* ot, s2vsa */

    uint32_t conditions = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_poll_health(&g_dev, &conditions));

    TEST_ASSERT_BITS_HIGH((uint32_t)TMC2209_UNDERVOLTAGE, conditions);
    TEST_ASSERT_BITS_HIGH((uint32_t)TMC2209_OVERTEMP_SHUTDOWN, conditions);
    TEST_ASSERT_BITS_HIGH((uint32_t)TMC2209_SHORT_CIRCUIT, conditions);
    TEST_ASSERT_BITS_LOW((uint32_t)TMC2209_DRIVER_RESET, conditions);
}

/* The driver came up holding defaults, so nothing commanded is still in it.
   Recovery is the caller re-sending its configuration; the library cannot do
   it, because eight registers have no read path. */
static void test_driver_reset_invalidates_every_owned_slot(void)
{
    setup_ready();
    TEST_ASSERT_TRUE(tmc2209_all_owned_valid(&g_dev));

    mock_set_reg(&g_mock, TMC2209_GSTAT, 0x1U);   /* reset */

    uint32_t conditions = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_poll_health(&g_dev, &conditions));
    TEST_ASSERT_BITS_HIGH((uint32_t)TMC2209_DRIVER_RESET, conditions);
    TEST_ASSERT_FALSE(tmc2209_all_owned_valid(&g_dev));

    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_INVALID_SLOT, tmc2209_read(&g_dev, TMC2209_VACTUAL, &v));

    /* Re-sending the configuration makes the owned slots valid again. */
    TEST_ASSERT_EQUAL(TMC2209_OK,
        tmc2209_write(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));
    TEST_ASSERT_TRUE(tmc2209_all_owned_valid(&g_dev));
}

/* GSTAT latches. Without an acknowledgement one brownout would report
   DRIVER_RESET on every later poll, re-invalidating the config that was just
   rewritten, forever. */
static void test_latched_conditions_survive_reconfiguration(void)
{
    setup_ready();
    mock_set_reg(&g_mock, TMC2209_GSTAT, 0x1U);

    uint32_t conditions = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_poll_health(&g_dev, &conditions));
    TEST_ASSERT_BITS_HIGH((uint32_t)TMC2209_DRIVER_RESET, conditions);

    TEST_ASSERT_EQUAL(TMC2209_OK,
        tmc2209_write(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));

    /* Still latched: rewriting the config does not clear a driver flag. */
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_poll_health(&g_dev, &conditions));
    TEST_ASSERT_BITS_HIGH((uint32_t)TMC2209_DRIVER_RESET, conditions);
    TEST_ASSERT_FALSE(tmc2209_all_owned_valid(&g_dev));

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_clear_faults(&g_dev, conditions));
    TEST_ASSERT_EQUAL(TMC2209_OK,
        tmc2209_write(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_poll_health(&g_dev, &conditions));
    TEST_ASSERT_EQUAL_HEX32(0, conditions);
    TEST_ASSERT_TRUE(tmc2209_all_owned_valid(&g_dev));
}

/* Polling must not have side effects, or two consecutive polls would disagree. */
static void test_poll_health_is_repeatable(void)
{
    setup_ready();
    mock_set_reg(&g_mock, TMC2209_GSTAT, 0x4U);   /* uv_cp */

    uint32_t first = 0;
    uint32_t second = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_poll_health(&g_dev, &first));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_poll_health(&g_dev, &second));
    TEST_ASSERT_EQUAL_HEX32(first, second);
    TEST_ASSERT_EQUAL_HEX32(0x4U, mock_reg(&g_mock, TMC2209_GSTAT));
}

/* Acknowledging says the reset was noticed, not that the config was rewritten. */
static void test_clear_faults_does_not_revalidate(void)
{
    setup_ready();
    mock_set_reg(&g_mock, TMC2209_GSTAT, 0x1U);

    uint32_t conditions = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_poll_health(&g_dev, &conditions));
    TEST_ASSERT_FALSE(tmc2209_all_owned_valid(&g_dev));

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_clear_faults(&g_dev, conditions));
    TEST_ASSERT_FALSE(tmc2209_all_owned_valid(&g_dev));
}

/* A flag that latches between the poll and the acknowledgement must survive to
   be reported, so only the acknowledged bits are written back. */
static void test_clear_faults_only_clears_what_it_was_told(void)
{
    setup_ready();
    mock_set_reg(&g_mock, TMC2209_GSTAT, 0x1U);            /* reset */

    uint32_t conditions = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_poll_health(&g_dev, &conditions));

    mock_set_reg(&g_mock, TMC2209_GSTAT, 0x5U);            /* uv_cp latches late */
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_clear_faults(&g_dev, conditions));

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_poll_health(&g_dev, &conditions));
    TEST_ASSERT_BITS_LOW((uint32_t)TMC2209_DRIVER_RESET, conditions);
    TEST_ASSERT_BITS_HIGH((uint32_t)TMC2209_UNDERVOLTAGE, conditions);
}

/* Live conditions have nothing to acknowledge, so passing them costs no wire. */
static void test_clear_faults_ignores_live_conditions(void)
{
    setup_ready();
    unsigned writes_before = g_mock.writes_seen;

    TEST_ASSERT_EQUAL(TMC2209_OK,
        tmc2209_clear_faults(&g_dev, (uint32_t)TMC2209_OVERTEMP_SHUTDOWN |
                                     (uint32_t)TMC2209_STANDSTILL));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_clear_faults(&g_dev, 0));

    TEST_ASSERT_EQUAL_UINT(writes_before, g_mock.writes_seen);
}

/* Open load reads true at standstill and at low current, so it is reported but
   kept out of the fault mask: treating it as a fault would trip continuously
   on a healthy motor. */
static void test_open_load_is_reported_but_is_not_a_fault(void)
{
    setup_ready();
    mock_set_reg(&g_mock, TMC2209_DRV_STATUS, (1U << 6) | (1U << 7));

    uint32_t conditions = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_poll_health(&g_dev, &conditions));
    TEST_ASSERT_BITS_HIGH((uint32_t)TMC2209_OPEN_LOAD, conditions);
    TEST_ASSERT_EQUAL_HEX32(0, conditions & TMC2209_CONDITIONS_FAULT);
}

/* StallGuard reports nothing outside the TCOOLTHRS window, and a zero
   threshold closes the window entirely, so the number means nothing. */
static void test_poll_load_is_invalid_when_stallguard_is_disabled(void)
{
    setup_ready();
    TEST_ASSERT_EQUAL(TMC2209_OK, write_one(TMC2209_TCOOLTHRS, 0));
    mock_set_reg(&g_mock, TMC2209_SG_RESULT, 300U);

    tmc2209_load_t load = { 0 };
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_poll_load(&g_dev, &load));
    TEST_ASSERT_EQUAL_UINT16(300, load.value);
    TEST_ASSERT_FALSE(load.usable);
}

static void test_poll_load_is_valid_once_the_window_is_open(void)
{
    setup_ready();
    mock_set_reg(&g_mock, TMC2209_SG_RESULT, 128U);

    tmc2209_load_t load = { 0 };
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_poll_load(&g_dev, &load));
    TEST_ASSERT_EQUAL_UINT16(128, load.value);
    TEST_ASSERT_TRUE(load.usable);   /* k_config sets TCOOLTHRS non-zero */
}

static void test_poll_pins_decodes_live_state(void)
{
    setup_ready();
    mock_set_reg(&g_mock, TMC2209_IOIN, MOCK_RESET_IOIN | (1U << 6) | (1U << 4));

    tmc2209_ioin_t pins = { false };
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_poll_pins(&g_dev, &pins));
    TEST_ASSERT_TRUE(pins.pdn_uart);
    TEST_ASSERT_TRUE(pins.diag);
    TEST_ASSERT_FALSE(pins.enn);
}

/* The diagnostic registers carry no condition worth naming, so they are
   reachable raw rather than wrapped, and a PC-side dump needs no passthrough. */
static void test_poll_raw_reaches_the_diagnostic_registers(void)
{
    setup_ready();
    mock_set_reg(&g_mock, TMC2209_MSCURACT, 0x00FFU | (0x101U << 16));

    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_poll_raw(&g_dev, TMC2209_MSCURACT, &v));

    tmc2209_mscuract_t m = tmc2209_mscuract_decode(v);
    TEST_ASSERT_EQUAL_INT16(255,  m.cur_a);
    TEST_ASSERT_EQUAL_INT16(-255, m.cur_b);
}

static void test_poll_raw_refuses_write_only_registers(void)
{
    setup_ready();
    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_ACCESS, tmc2209_poll_raw(&g_dev, TMC2209_VACTUAL, &v));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ACCESS, tmc2209_poll_raw(&g_dev, TMC2209_IHOLD_IRUN, &v));
}

/* What the device answers says nothing about who owns the value, so one stray
   read must not stand in for a write that never happened. */
static void test_poll_raw_does_not_update_the_cache(void)
{
    setup_ready();
    mock_set_reg(&g_mock, TMC2209_GCONF, 0xDEADU);

    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_poll_raw(&g_dev, TMC2209_GCONF, &v));
    TEST_ASSERT_EQUAL_HEX32(0xDEADU, v);

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_read(&g_dev, TMC2209_GCONF, &v));
    TEST_ASSERT_EQUAL_HEX32(CFG_GCONF, v);
}

/* ── Verdicts ───────────────────────────────────────────────────────────── */

/* The revision is carried, never recognised: no value is special to the
   library, so every value comes back as it was found. Whether to accept one is
   the caller's policy, exactly as with the retry thresholds. */
static void test_poll_version_reports_whatever_the_part_answers(void)
{
    static const uint8_t revisions[] = { 0x00, 0x20, 0x21, 0x22, 0xFF };

    for (size_t i = 0; i < sizeof revisions / sizeof revisions[0]; i++) {
        setup_ready();
        mock_set_reg(&g_mock, TMC2209_IOIN, (uint32_t)revisions[i] << 24);

        uint8_t version = 0;
        TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_poll_version(&g_dev, &version));
        TEST_ASSERT_EQUAL_HEX8(revisions[i], version);
    }
}

/* IOIN carries both, but the two answer different questions and are read
   through different calls. */
static void test_poll_version_and_poll_pins_read_the_same_register(void)
{
    setup_ready();
    mock_set_reg(&g_mock, TMC2209_IOIN, (0x5AU << 24) | (1U << 6));

    uint8_t version = 0;
    tmc2209_ioin_t pins = { false };
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_poll_version(&g_dev, &version));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_poll_pins(&g_dev, &pins));

    TEST_ASSERT_EQUAL_HEX8(0x5A, version);
    TEST_ASSERT_TRUE(pins.pdn_uart);
}

static void test_verify_config_agrees_after_bringup(void)
{
    setup_ready();
    uint32_t mismatched = 0xFFFFU;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_verify_config(&g_dev, &mismatched));
    TEST_ASSERT_EQUAL_HEX32(0, mismatched);
}

/* The test that validates the caching scheme itself: if the driver ever
   disagrees with the cache, this is what says so. */
static void test_verify_config_reports_a_disagreeing_register(void)
{
    setup_ready();
    mock_set_reg(&g_mock, TMC2209_CHOPCONF, 0x00000001U);

    uint32_t mismatched = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_MISMATCH, tmc2209_verify_config(&g_dev, &mismatched));
    TEST_ASSERT_EQUAL_HEX32(1U << tmc2209_reg_slot(TMC2209_CHOPCONF), mismatched);
}

/* ── Runtime writes ─────────────────────────────────────────────────────── */

static void test_set_velocity_writes_and_is_recallable(void)
{
    setup_ready();
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_set_velocity(&g_dev, -1000));
    TEST_ASSERT_EQUAL_HEX32(tmc2209_vactual_encode(-1000),
                            mock_reg(&g_mock, TMC2209_VACTUAL));

    /* VACTUAL cannot be read back from the driver, so the cache is the only place
       the coordinated-motion precondition can be checked. */
    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_read(&g_dev, TMC2209_VACTUAL, &v));
    TEST_ASSERT_EQUAL_INT32(-1000, tmc2209_vactual_decode(v));

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_set_velocity(&g_dev, 0));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_read(&g_dev, TMC2209_VACTUAL, &v));
    TEST_ASSERT_EQUAL_INT32(0, tmc2209_vactual_decode(v));
}

static void test_set_current_writes_ihold_irun(void)
{
    setup_ready();
    const tmc2209_ihold_irun_t c = { .ihold = 4, .irun = 20, .iholddelay = 6 };
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_set_current(&g_dev, &c));

    tmc2209_ihold_irun_t back =
        tmc2209_ihold_irun_decode(mock_reg(&g_mock, TMC2209_IHOLD_IRUN));
    TEST_ASSERT_EQUAL_UINT8(4,  back.ihold);
    TEST_ASSERT_EQUAL_UINT8(20, back.irun);
    TEST_ASSERT_EQUAL_UINT8(6,  back.iholddelay);
}

/* ── Fault injection ────────────────────────────────────────────────────── */

static void test_crc_failure_recovers_on_retry(void)
{
    setup_uart(0, true, 1);
    TEST_ASSERT_EQUAL(TMC2209_OK,
        tmc2209_bringup(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));

    g_mock.fail_crc = 1;
    mock_set_reg(&g_mock, TMC2209_SG_RESULT, 77U);

    tmc2209_load_t load = { 0 };
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_poll_load(&g_dev, &load));
    TEST_ASSERT_EQUAL_UINT16(77, load.value);
}

static void test_crc_failure_beyond_retries_is_reported(void)
{
    setup_uart(0, true, 1);
    TEST_ASSERT_EQUAL(TMC2209_OK,
        tmc2209_bringup(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));

    g_mock.fail_crc = 5;
    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_CRC, tmc2209_poll_raw(&g_dev, TMC2209_MSCNT, &v));
}

/* A mismatch between what went out and what came back means something else
   drove the line, which is the cheapest collision detector available. */
static void test_echo_mismatch_is_detected(void)
{
    setup_uart(0, true, 0);
    g_mock.corrupt_echo = 1;

    TEST_ASSERT_EQUAL(TMC2209_ERR_ECHO,
        tmc2209_bringup(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));
}

static void test_silence_from_the_driver_times_out(void)
{
    setup_uart(0, true, 0);
    g_mock.drop_reply = 1;

    TEST_ASSERT_EQUAL(TMC2209_ERR_RX_TIMEOUT,
        tmc2209_bringup(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));
}

/* An intact reply naming a register nobody asked for: the reply stream has
   slipped a transaction. Not retried, so the read count stays at one. */
static void test_wrong_register_reply_fails_without_retrying(void)
{
    setup_uart(0, true, 3);
    g_mock.wrong_reg = 1;
    unsigned reads_before = g_mock.reads_seen;

    TEST_ASSERT_EQUAL(TMC2209_ERR_REG,
        tmc2209_bringup(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));
    TEST_ASSERT_EQUAL_UINT(1, g_mock.reads_seen - reads_before);
}

/* The SIL backend is full duplex, so nothing comes back on rx but the reply. */
static void test_non_echoing_backend_works(void)
{
    setup_uart(0, false, 1);
    TEST_ASSERT_EQUAL(TMC2209_OK,
        tmc2209_bringup(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));
    TEST_ASSERT_TRUE(tmc2209_all_owned_valid(&g_dev));
}

/* ── Passthrough ────────────────────────────────────────────────────────── */

static void test_passthrough_moves_bytes_verbatim(void)
{
    setup_ready();
    mock_set_reg(&g_mock, TMC2209_MSCNT, 0x1234U);

    uint8_t req[TMC2209_READ_REQ_LEN];
    tmc2209_frame_read_request(req, 0, (uint8_t)TMC2209_MSCNT);

    uint8_t reply[TMC2209_REPLY_LEN] = { 0 };
    size_t got = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK,
        tmc2209_uart_send(&g_uart, req, sizeof req, reply, sizeof reply, &got));
    TEST_ASSERT_EQUAL_size_t(sizeof reply, got);

    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK,
        tmc2209_frame_parse_reply(reply, (uint8_t)TMC2209_MSCNT, &v));
    TEST_ASSERT_EQUAL_HEX32(0x1234U, v);
}

/* Silence and a severed reply are different faults at different ends of the
   cable, and the count is the only thing that tells them apart. */
static void test_passthrough_reports_silence_as_zero_bytes(void)
{
    setup_ready();
    g_mock.drop_reply = 1;

    uint8_t req[TMC2209_READ_REQ_LEN];
    tmc2209_frame_read_request(req, 0, (uint8_t)TMC2209_MSCNT);

    uint8_t reply[TMC2209_REPLY_LEN] = { 0 };
    size_t got = 99;
    TEST_ASSERT_EQUAL(TMC2209_ERR_RX_TIMEOUT,
        tmc2209_uart_send(&g_uart, req, sizeof req, reply, sizeof reply, &got));
    TEST_ASSERT_EQUAL_size_t(0, got);
}

static void test_passthrough_reports_a_partial_reply(void)
{
    setup_ready();
    g_mock.truncate_reply = 1;
    g_mock.reply_keep     = 5;

    uint8_t req[TMC2209_READ_REQ_LEN];
    tmc2209_frame_read_request(req, 0, (uint8_t)TMC2209_MSCNT);

    uint8_t reply[TMC2209_REPLY_LEN] = { 0 };
    size_t got = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_RX_TIMEOUT,
        tmc2209_uart_send(&g_uart, req, sizeof req, reply, sizeof reply, &got));
    TEST_ASSERT_EQUAL_size_t(5, got);

    /* The bytes that did arrive are the real ones, which is what makes them
       worth handing back. */
    TEST_ASSERT_EQUAL_HEX8(TMC2209_SYNC, reply[0]);
    TEST_ASSERT_EQUAL_HEX8(TMC2209_MASTER_ADDR, reply[1]);
}

/* Our own bytes failing to return is a fault on the transmit side. Reporting it
   as a timeout would send someone to the far end of the cable. */
static void test_passthrough_short_echo_is_not_a_driver_timeout(void)
{
    setup_ready();
    g_mock.truncate_echo = 1;
    g_mock.echo_keep     = 2;

    uint8_t req[TMC2209_READ_REQ_LEN];
    tmc2209_frame_read_request(req, 0, (uint8_t)TMC2209_MSCNT);

    uint8_t reply[TMC2209_REPLY_LEN] = { 0 };
    TEST_ASSERT_EQUAL(TMC2209_ERR_ECHO,
        tmc2209_uart_send(&g_uart, req, sizeof req, reply, sizeof reply, NULL));
}

/* A collision does not gag the driver, so the answer is still collected. */
static void test_passthrough_echo_mismatch_still_collects_the_reply(void)
{
    setup_ready();
    mock_set_reg(&g_mock, TMC2209_MSCNT, 0x1234U);
    g_mock.corrupt_echo = 1;

    uint8_t req[TMC2209_READ_REQ_LEN];
    tmc2209_frame_read_request(req, 0, (uint8_t)TMC2209_MSCNT);

    uint8_t reply[TMC2209_REPLY_LEN] = { 0 };
    size_t got = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_ECHO,
        tmc2209_uart_send(&g_uart, req, sizeof req, reply, sizeof reply, &got));
    TEST_ASSERT_EQUAL_size_t(sizeof reply, got);

    uint32_t v = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK,
        tmc2209_frame_parse_reply(reply, (uint8_t)TMC2209_MSCNT, &v));
    TEST_ASSERT_EQUAL_HEX32(0x1234U, v);
}

/* Bytes the library did not build are bytes it cannot account for, including
   the IFCNT they advanced. */
static void test_passthrough_write_desyncs_until_invalidated(void)
{
    setup_ready();

    uint8_t dg[TMC2209_WRITE_LEN];
    tmc2209_frame_write(dg, 0, (uint8_t)TMC2209_SGTHRS, 0x99U);
    TEST_ASSERT_EQUAL(TMC2209_OK,
        tmc2209_uart_send(&g_uart, dg, sizeof dg, NULL, 0, NULL));

    tmc2209_invalidate_owned(&g_dev);
    TEST_ASSERT_FALSE(tmc2209_all_owned_valid(&g_dev));

    /* The next batch re-seeds the IFCNT baseline, or it would fail against a
       counter that moved without it. */
    TEST_ASSERT_EQUAL(TMC2209_OK,
        tmc2209_write(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));
    TEST_ASSERT_TRUE(tmc2209_all_owned_valid(&g_dev));
    TEST_ASSERT_EQUAL_HEX32(0x00000050U, mock_reg(&g_mock, TMC2209_SGTHRS));
}

static void test_passthrough_rejects_oversized_frames(void)
{
    setup_ready();
    uint8_t big[64] = { 0 };
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG,
        tmc2209_uart_send(&g_uart, big, sizeof big, NULL, 0, NULL));
    TEST_ASSERT_EQUAL(TMC2209_ERR_ARG,
        tmc2209_uart_send(&g_uart, big, 0, NULL, 0, NULL));
}

void run_device_tests(void)
{
    RUN_TEST(test_init_leaves_every_slot_invalid);
    RUN_TEST(test_construction_does_no_io);
    RUN_TEST(test_init_rejects_out_of_range_address);

    RUN_TEST(test_attach_uart_rejects_an_incomplete_backend);
    RUN_TEST(test_a_rejected_uart_does_not_displace_the_attached_one);
    RUN_TEST(test_a_device_without_a_uart_refuses_every_transaction);
    RUN_TEST(test_detaching_the_uart_stops_transactions);
    RUN_TEST(test_reattaching_a_uart_keeps_the_cache);
    RUN_TEST(test_two_devices_share_one_uart);

    RUN_TEST(test_bringup_writes_the_whole_configuration);
    RUN_TEST(test_bringup_never_writes_a_value_the_caller_did_not_supply);
    RUN_TEST(test_bringup_rejects_a_configuration_with_a_gap);
    RUN_TEST(test_bringup_rejects_a_register_it_does_not_own);
    RUN_TEST(test_bringup_refuses_a_configuration_that_asks_for_motion);
    RUN_TEST(test_velocity_is_free_to_move_after_bringup);
    RUN_TEST(test_bringup_reads_constant_registers_off_the_part);
    RUN_TEST(test_bringup_clears_latched_gstat);
    RUN_TEST(test_bringup_reports_the_flags_it_clears);
    RUN_TEST(test_bringup_fails_when_the_addressed_driver_is_absent);
    RUN_TEST(test_addressing_reaches_the_right_driver);

    RUN_TEST(test_read_answers_owned_registers_from_the_cache);
    RUN_TEST(test_read_refuses_volatile_registers);
    RUN_TEST(test_read_rejects_an_unknown_register);
    RUN_TEST(test_read_refuses_an_invalidated_slot);

    RUN_TEST(test_write_lands_on_the_device_and_updates_the_cache);
    RUN_TEST(test_write_verifies_the_batch_once);
    RUN_TEST(test_write_skips_ops_that_change_nothing);
    RUN_TEST(test_write_sends_only_the_op_that_changed);
    RUN_TEST(test_write_applies_the_last_value_for_a_repeated_register);
    RUN_TEST(test_write_rejects_a_register_it_does_not_own);
    RUN_TEST(test_write_validates_the_whole_batch_before_sending);
    RUN_TEST(test_write_rejects_an_empty_batch);
    RUN_TEST(test_a_failed_batch_invalidates_every_slot_in_it);
    RUN_TEST(test_a_write_the_device_never_counted_is_reported);
    RUN_TEST(test_failed_at_is_n_when_the_batch_check_fails);

    RUN_TEST(test_poll_health_is_clear_on_a_healthy_driver);
    RUN_TEST(test_poll_health_merges_both_registers);
    RUN_TEST(test_driver_reset_invalidates_every_owned_slot);
    RUN_TEST(test_latched_conditions_survive_reconfiguration);
    RUN_TEST(test_poll_health_is_repeatable);
    RUN_TEST(test_clear_faults_does_not_revalidate);
    RUN_TEST(test_clear_faults_only_clears_what_it_was_told);
    RUN_TEST(test_clear_faults_ignores_live_conditions);
    RUN_TEST(test_open_load_is_reported_but_is_not_a_fault);
    RUN_TEST(test_poll_load_is_invalid_when_stallguard_is_disabled);
    RUN_TEST(test_poll_load_is_valid_once_the_window_is_open);
    RUN_TEST(test_poll_pins_decodes_live_state);
    RUN_TEST(test_poll_raw_reaches_the_diagnostic_registers);
    RUN_TEST(test_poll_raw_refuses_write_only_registers);
    RUN_TEST(test_poll_raw_does_not_update_the_cache);

    RUN_TEST(test_poll_version_reports_whatever_the_part_answers);
    RUN_TEST(test_poll_version_and_poll_pins_read_the_same_register);
    RUN_TEST(test_verify_config_agrees_after_bringup);
    RUN_TEST(test_verify_config_reports_a_disagreeing_register);

    RUN_TEST(test_set_velocity_writes_and_is_recallable);
    RUN_TEST(test_set_current_writes_ihold_irun);

    RUN_TEST(test_crc_failure_recovers_on_retry);
    RUN_TEST(test_crc_failure_beyond_retries_is_reported);
    RUN_TEST(test_echo_mismatch_is_detected);
    RUN_TEST(test_silence_from_the_driver_times_out);
    RUN_TEST(test_wrong_register_reply_fails_without_retrying);
    RUN_TEST(test_non_echoing_backend_works);

    RUN_TEST(test_passthrough_moves_bytes_verbatim);
    RUN_TEST(test_passthrough_reports_silence_as_zero_bytes);
    RUN_TEST(test_passthrough_reports_a_partial_reply);
    RUN_TEST(test_passthrough_short_echo_is_not_a_driver_timeout);
    RUN_TEST(test_passthrough_echo_mismatch_still_collects_the_reply);
    RUN_TEST(test_passthrough_write_desyncs_until_invalidated);
    RUN_TEST(test_passthrough_rejects_oversized_frames);
}
