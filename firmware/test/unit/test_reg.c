/*
 * test_reg.c — the register table and the field codecs.
 *
 * The access-flag tests matter more than they look. Reading a write-only
 * register is the defect the Python library shipped, and the table is where
 * that becomes impossible rather than merely discouraged.
 */

#include "unity.h"
#include "tmc2209_reg.h"

static void test_every_slot_is_unique_and_round_trips(void)
{
    for (int slot = 0; slot < TMC2209_REG_COUNT; slot++) {
        TEST_ASSERT_EQUAL_INT(slot, tmc2209_reg_slot(tmc2209_reg_at(slot)));
    }
}

/* The dirty bitmap is a single word, which is the hard cap on how many
   registers the table can carry. */
static void test_register_count_fits_the_dirty_bitmap(void)
{
    TEST_ASSERT_LESS_OR_EQUAL_INT(32, TMC2209_REG_COUNT);
    TEST_ASSERT_EQUAL_INT(23, TMC2209_REG_COUNT);
}

/* Capability, not policy: a register being outside our configuration set must
   not make it unreachable, or the PC diagnostic has to hand-assemble
   passthrough datagrams to see the whole device. */
static void test_diagnostic_registers_are_readable_but_never_configured(void)
{
    const tmc2209_reg_t diagnostic[] = {
        TMC2209_OTP_READ, TMC2209_MSCURACT,
        TMC2209_PWMCONF,  TMC2209_PWM_SCALE, TMC2209_PWM_AUTO,
    };
    for (size_t i = 0; i < sizeof diagnostic / sizeof diagnostic[0]; i++) {
        uint8_t access = tmc2209_reg_access(diagnostic[i]);
        TEST_ASSERT_BITS_HIGH(TMC2209_ACC_R, access);
        TEST_ASSERT_BITS_LOW(TMC2209_ACC_W, access);
        TEST_ASSERT_BITS_LOW(TMC2209_ACC_CONFIG, access);
    }
}

/* PWMCONF is R/W in silicon. Our policy makes it read-only, because
   pwm_autoscale and pwm_autograd tune it better than we would. */
static void test_pwmconf_is_readable_but_not_writable(void)
{
    TEST_ASSERT_NOT_EQUAL(-1, tmc2209_reg_slot(TMC2209_PWMCONF));
    TEST_ASSERT_BITS_LOW(TMC2209_ACC_W, tmc2209_reg_access(TMC2209_PWMCONF));
    TEST_ASSERT_EQUAL_HEX32(0xC10D0024u, tmc2209_reg_reset_value(TMC2209_PWMCONF));
}

/* OTP_PROG burns one-time fuses. Hand-assembling a passthrough datagram is
   the right amount of friction for something irreversible. */
static void test_otp_prog_stays_unreachable(void)
{
    TEST_ASSERT_EQUAL_INT(-1, tmc2209_reg_slot((tmc2209_reg_t)0x04));
}

static void test_write_only_registers_are_not_readable(void)
{
    const tmc2209_reg_t write_only[] = {
        TMC2209_SLAVECONF, TMC2209_IHOLD_IRUN, TMC2209_TPOWERDOWN,
        TMC2209_TPWMTHRS,  TMC2209_TCOOLTHRS,  TMC2209_VACTUAL,
        TMC2209_SGTHRS,    TMC2209_COOLCONF,
    };
    for (size_t i = 0; i < sizeof write_only / sizeof write_only[0]; i++) {
        uint8_t access = tmc2209_reg_access(write_only[i]);
        TEST_ASSERT_BITS_LOW(TMC2209_ACC_R, access);
        TEST_ASSERT_BITS_HIGH(TMC2209_ACC_W, access);
    }
    TEST_ASSERT_EQUAL_INT(8, (int)(sizeof write_only / sizeof write_only[0]));
}

static void test_read_only_registers_are_not_writable(void)
{
    const tmc2209_reg_t read_only[] = {
        TMC2209_IFCNT, TMC2209_IOIN, TMC2209_TSTEP,
        TMC2209_SG_RESULT, TMC2209_MSCNT, TMC2209_DRV_STATUS,
        TMC2209_OTP_READ, TMC2209_MSCURACT, TMC2209_PWM_SCALE, TMC2209_PWM_AUTO,
    };
    for (size_t i = 0; i < sizeof read_only / sizeof read_only[0]; i++) {
        TEST_ASSERT_BITS_LOW(TMC2209_ACC_W, tmc2209_reg_access(read_only[i]));
    }
}

/* FACTORY_CONF is R/W in silicon, but writing it overwrites the factory
   oscillator trim and detunes every timing-derived quantity. The Python
   library did exactly that on every init. */
static void test_factory_conf_is_read_only_to_us(void)
{
    uint8_t access = tmc2209_reg_access(TMC2209_FACTORY_CONF);
    TEST_ASSERT_BITS_HIGH(TMC2209_ACC_R, access);
    TEST_ASSERT_BITS_LOW(TMC2209_ACC_W, access);
    TEST_ASSERT_BITS_LOW(TMC2209_ACC_CONFIG, access);
}

/* Writing GSTAT clears latched flags rather than restoring configuration, so
   it must not ride along in a reflush. */
static void test_gstat_is_writable_but_not_config(void)
{
    uint8_t access = tmc2209_reg_access(TMC2209_GSTAT);
    TEST_ASSERT_BITS_HIGH(TMC2209_ACC_W, access);
    TEST_ASSERT_BITS_LOW(TMC2209_ACC_CONFIG, access);
}

static void test_config_registers_are_all_writable(void)
{
    for (int slot = 0; slot < TMC2209_REG_COUNT; slot++) {
        uint8_t access = tmc2209_reg_access_at(slot);
        if (access & TMC2209_ACC_CONFIG) {
            TEST_ASSERT_BITS_HIGH(TMC2209_ACC_W, access);
        }
    }
}

static void test_reset_values_match_the_datasheet(void)
{
    TEST_ASSERT_EQUAL_HEX32(0x00000101u, tmc2209_reg_reset_value(TMC2209_GCONF));
    TEST_ASSERT_EQUAL_HEX32(0x10000053u, tmc2209_reg_reset_value(TMC2209_CHOPCONF));
    TEST_ASSERT_EQUAL_HEX32(0x00071703u, tmc2209_reg_reset_value(TMC2209_IHOLD_IRUN));
    TEST_ASSERT_EQUAL_HEX32(0x00000014u, tmc2209_reg_reset_value(TMC2209_TPOWERDOWN));
}

static void test_chopconf_reset_decodes_to_256_microsteps_interpolated(void)
{
    tmc2209_chopconf_t c = tmc2209_chopconf_decode(0x10000053u);
    TEST_ASSERT_EQUAL_UINT8(3, c.toff);
    TEST_ASSERT_EQUAL_UINT8(5, c.hstrt);
    TEST_ASSERT_EQUAL_UINT8(0, c.hend);
    TEST_ASSERT_EQUAL(TMC2209_MRES_256, c.mres);
    TEST_ASSERT_TRUE(c.intpol);
    TEST_ASSERT_FALSE(c.dedge);
}

static void test_ihold_irun_reset_decodes(void)
{
    tmc2209_ihold_irun_t i = tmc2209_ihold_irun_decode(0x00071703u);
    TEST_ASSERT_EQUAL_UINT8(3,  i.ihold);
    TEST_ASSERT_EQUAL_UINT8(23, i.irun);
    TEST_ASSERT_EQUAL_UINT8(7,  i.iholddelay);
}

static void test_gconf_round_trips(void)
{
    tmc2209_gconf_t g = {
        .pdn_disable = true, .mstep_reg_select = true,
        .multistep_filt = true, .shaft = true,
    };
    uint32_t raw = tmc2209_gconf_encode(&g);
    tmc2209_gconf_t back = tmc2209_gconf_decode(raw);

    TEST_ASSERT_TRUE(back.pdn_disable);
    TEST_ASSERT_TRUE(back.mstep_reg_select);
    TEST_ASSERT_TRUE(back.multistep_filt);
    TEST_ASSERT_TRUE(back.shaft);
    TEST_ASSERT_FALSE(back.en_spreadcycle);
    TEST_ASSERT_FALSE(back.test_mode);
    TEST_ASSERT_EQUAL_HEX32(raw, tmc2209_gconf_encode(&back));
}

static void test_chopconf_round_trips(void)
{
    tmc2209_chopconf_t c = {
        .toff = 5, .hstrt = 4, .hend = 1, .tbl = TMC2209_TBL_24,
        .vsense = true, .mres = TMC2209_MRES_16, .intpol = true, .diss2vs = true,
    };
    tmc2209_chopconf_t back = tmc2209_chopconf_decode(tmc2209_chopconf_encode(&c));

    TEST_ASSERT_EQUAL_UINT8(5, back.toff);
    TEST_ASSERT_EQUAL_UINT8(4, back.hstrt);
    TEST_ASSERT_EQUAL_UINT8(1, back.hend);
    TEST_ASSERT_EQUAL(TMC2209_TBL_24, back.tbl);
    TEST_ASSERT_TRUE(back.vsense);
    TEST_ASSERT_EQUAL(TMC2209_MRES_16, back.mres);
    TEST_ASSERT_TRUE(back.intpol);
    TEST_ASSERT_TRUE(back.diss2vs);
    TEST_ASSERT_FALSE(back.diss2g);
}

static void test_ihold_irun_and_coolconf_round_trip(void)
{
    tmc2209_ihold_irun_t i = { .ihold = 8, .irun = 31, .iholddelay = 15 };
    tmc2209_ihold_irun_t bi = tmc2209_ihold_irun_decode(tmc2209_ihold_irun_encode(&i));
    TEST_ASSERT_EQUAL_UINT8(8,  bi.ihold);
    TEST_ASSERT_EQUAL_UINT8(31, bi.irun);
    TEST_ASSERT_EQUAL_UINT8(15, bi.iholddelay);

    tmc2209_coolconf_t c = {
        .semin = 5, .seup = TMC2209_SEUP_4, .semax = 2,
        .sedn = TMC2209_SEDN_2, .seimin = true,
    };
    tmc2209_coolconf_t bc = tmc2209_coolconf_decode(tmc2209_coolconf_encode(&c));
    TEST_ASSERT_EQUAL_UINT8(5, bc.semin);
    TEST_ASSERT_EQUAL(TMC2209_SEUP_4, bc.seup);
    TEST_ASSERT_EQUAL_UINT8(2, bc.semax);
    TEST_ASSERT_EQUAL(TMC2209_SEDN_2, bc.sedn);
    TEST_ASSERT_TRUE(bc.seimin);
}

static void test_mres_maps_to_microsteps(void)
{
    TEST_ASSERT_EQUAL_UINT16(256, tmc2209_mres_microsteps(TMC2209_MRES_256));
    TEST_ASSERT_EQUAL_UINT16(16,  tmc2209_mres_microsteps(TMC2209_MRES_16));
    TEST_ASSERT_EQUAL_UINT16(1,   tmc2209_mres_microsteps(TMC2209_MRES_FULL));
}

static void test_drv_status_decodes_faults(void)
{
    tmc2209_drv_status_t s = tmc2209_drv_status_decode(0x80170002u);
    TEST_ASSERT_TRUE(s.ot);
    TEST_ASSERT_FALSE(s.otpw);
    TEST_ASSERT_EQUAL_UINT8(0x17, s.cs_actual);
    TEST_ASSERT_TRUE(s.stst);
    TEST_ASSERT_TRUE(tmc2209_drv_status_faulted(&s));
}

/* Open load reads true at standstill and at low current, so treating it as a
   fault would trip continuously on a healthy motor. */
static void test_open_load_alone_is_not_a_fault(void)
{
    tmc2209_drv_status_t s = tmc2209_drv_status_decode((1u << 6) | (1u << 7));
    TEST_ASSERT_TRUE(s.ola);
    TEST_ASSERT_TRUE(s.olb);
    TEST_ASSERT_FALSE(tmc2209_drv_status_faulted(&s));
}

static void test_ioin_decodes_version(void)
{
    tmc2209_ioin_t i = tmc2209_ioin_decode(0x21000000u | (1u << 6));
    TEST_ASSERT_EQUAL_HEX8(TMC2209_IOIN_VERSION, i.version);
    TEST_ASSERT_TRUE(i.pdn_uart);
    TEST_ASSERT_FALSE(i.enn);
}

static void test_vactual_sign_extends(void)
{
    TEST_ASSERT_EQUAL_INT32(0,      tmc2209_vactual_decode(0x000000u));
    TEST_ASSERT_EQUAL_INT32(1000,   tmc2209_vactual_decode(1000u));
    TEST_ASSERT_EQUAL_INT32(-1,     tmc2209_vactual_decode(0xFFFFFFu));
    TEST_ASSERT_EQUAL_INT32(-1000,  tmc2209_vactual_decode(0x1000000u - 1000u));
}

/* Both phases are 9-bit two's complement, which is the awkward part and the
   only reason these registers get decoders at all. */
static void test_mscuract_sign_extends_both_phases(void)
{
    tmc2209_mscuract_t m = tmc2209_mscuract_decode(0u);
    TEST_ASSERT_EQUAL_INT16(0, m.cur_a);
    TEST_ASSERT_EQUAL_INT16(0, m.cur_b);

    /* Peak positive on A (+255), peak negative on B (-255). */
    m = tmc2209_mscuract_decode(0x00FFu | (0x101u << 16));
    TEST_ASSERT_EQUAL_INT16(255,  m.cur_a);
    TEST_ASSERT_EQUAL_INT16(-255, m.cur_b);

    /* Quarter cycle apart: A at zero crossing, B at -1. */
    m = tmc2209_mscuract_decode(0x0000u | (0x1FFu << 16));
    TEST_ASSERT_EQUAL_INT16(0,  m.cur_a);
    TEST_ASSERT_EQUAL_INT16(-1, m.cur_b);
}

static void test_pwm_scale_and_auto_decode(void)
{
    tmc2209_pwm_scale_t p = tmc2209_pwm_scale_decode(0x01FF0080u);
    TEST_ASSERT_EQUAL_UINT8(0x80, p.sum);
    TEST_ASSERT_EQUAL_INT16(-1, p.automatic);   /* signed, unlike sum */

    tmc2209_pwm_auto_t a = tmc2209_pwm_auto_decode(0x000E0024u);
    TEST_ASSERT_EQUAL_UINT8(0x24, a.ofs_auto);
    TEST_ASSERT_EQUAL_UINT8(0x0E, a.grad_auto);
}

static void test_gstat_round_trips(void)
{
    tmc2209_gstat_t g = tmc2209_gstat_decode(0x5u);
    TEST_ASSERT_TRUE(g.reset);
    TEST_ASSERT_FALSE(g.drv_err);
    TEST_ASSERT_TRUE(g.uv_cp);
    TEST_ASSERT_EQUAL_HEX32(0x5u, tmc2209_gstat_encode(&g));
}

void run_reg_tests(void)
{
    RUN_TEST(test_every_slot_is_unique_and_round_trips);
    RUN_TEST(test_register_count_fits_the_dirty_bitmap);
    RUN_TEST(test_diagnostic_registers_are_readable_but_never_configured);
    RUN_TEST(test_pwmconf_is_readable_but_not_writable);
    RUN_TEST(test_otp_prog_stays_unreachable);
    RUN_TEST(test_write_only_registers_are_not_readable);
    RUN_TEST(test_read_only_registers_are_not_writable);
    RUN_TEST(test_factory_conf_is_read_only_to_us);
    RUN_TEST(test_gstat_is_writable_but_not_config);
    RUN_TEST(test_config_registers_are_all_writable);
    RUN_TEST(test_reset_values_match_the_datasheet);
    RUN_TEST(test_chopconf_reset_decodes_to_256_microsteps_interpolated);
    RUN_TEST(test_ihold_irun_reset_decodes);
    RUN_TEST(test_gconf_round_trips);
    RUN_TEST(test_chopconf_round_trips);
    RUN_TEST(test_ihold_irun_and_coolconf_round_trip);
    RUN_TEST(test_mres_maps_to_microsteps);
    RUN_TEST(test_drv_status_decodes_faults);
    RUN_TEST(test_open_load_alone_is_not_a_fault);
    RUN_TEST(test_ioin_decodes_version);
    RUN_TEST(test_vactual_sign_extends);
    RUN_TEST(test_mscuract_sign_extends_both_phases);
    RUN_TEST(test_pwm_scale_and_auto_decode);
    RUN_TEST(test_gstat_round_trips);
}
