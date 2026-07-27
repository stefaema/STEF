/*
 * test_reg.c: the register table, its classification, and the field codecs.
 *
 * The classification tests are the point of this file. Access says what the
 * driver permits; class says who can change the value. Confusing the two is
 * what let GSTAT be treated as cacheable when hardware sets its flags, and
 * what kept PWMCONF uncacheable when nothing writes it at all.
 */

#include "unity.h"
#include "tmc2209_reg.h"

static int count_class(tmc2209_class_t cls)
{
    int n = 0;
    for (int slot = 0; slot < TMC2209_REG_COUNT; slot++) {
        if (tmc2209_reg_class_at(slot) == cls) {
            n++;
        }
    }
    return n;
}

/* ── Table shape ────────────────────────────────────────────────────────── */

static void test_every_slot_is_unique_and_round_trips(void)
{
    for (int slot = 0; slot < TMC2209_REG_COUNT; slot++) {
        TEST_ASSERT_EQUAL_INT(slot, tmc2209_reg_slot(tmc2209_reg_at(slot)));
    }
}

/* The validity bitmap is a single word, which is the hard cap on how many
   registers the table can carry. */
static void test_register_count_fits_the_validity_bitmap(void)
{
    TEST_ASSERT_LESS_OR_EQUAL_INT(32, TMC2209_REG_COUNT);
    TEST_ASSERT_EQUAL_INT(23, TMC2209_REG_COUNT);
}

static void test_every_register_is_classified(void)
{
    for (int slot = 0; slot < TMC2209_REG_COUNT; slot++) {
        TEST_ASSERT_NOT_EQUAL(TMC2209_CLASS_UNKNOWN, tmc2209_reg_class_at(slot));
    }
}

static void test_class_counts_are_ten_ten_three(void)
{
    TEST_ASSERT_EQUAL_INT(10, count_class(TMC2209_CLASS_VOLATILE));
    TEST_ASSERT_EQUAL_INT(10, count_class(TMC2209_CLASS_OWNED));
    TEST_ASSERT_EQUAL_INT(3,  count_class(TMC2209_CLASS_CONSTANT));
    TEST_ASSERT_EQUAL_INT(TMC2209_OWNED_COUNT, count_class(TMC2209_CLASS_OWNED));
}

/* OTP_PROG burns one-time fuses. Hand-assembling a passthrough datagram is the
   right amount of friction for something irreversible. */
static void test_otp_prog_stays_unreachable(void)
{
    TEST_ASSERT_EQUAL_INT(-1, tmc2209_reg_slot((tmc2209_reg_t)0x04));
    TEST_ASSERT_EQUAL(TMC2209_CLASS_UNKNOWN, tmc2209_reg_class((tmc2209_reg_t)0x04));
    TEST_ASSERT_EQUAL_UINT8(0, tmc2209_reg_access((tmc2209_reg_t)0x04));
}

/* ── Classification ─────────────────────────────────────────────────────── */

static void test_volatile_registers_are_the_ones_hardware_writes(void)
{
    const tmc2209_reg_t hardware_writes[] = {
        TMC2209_GSTAT,      /* latches fault flags */
        TMC2209_IFCNT,      /* increments on accepted writes */
        TMC2209_IOIN,       /* live pin state */
        TMC2209_TSTEP,      /* measures the received step period */
        TMC2209_SG_RESULT,  /* back-EMF load estimate */
        TMC2209_MSCNT,      /* advances with steps */
        TMC2209_DRV_STATUS, TMC2209_MSCURACT, TMC2209_PWM_SCALE, TMC2209_PWM_AUTO,
    };
    for (size_t i = 0; i < sizeof hardware_writes / sizeof hardware_writes[0]; i++) {
        TEST_ASSERT_EQUAL(TMC2209_CLASS_VOLATILE, tmc2209_reg_class(hardware_writes[i]));
    }
}

/* GSTAT is readable and writable, so an access-based rule would have made it
   cacheable. Hardware sets its flags, so a cached copy could report no reset
   on a driver that browned out a second ago. */
static void test_gstat_is_volatile_despite_being_writable(void)
{
    TEST_ASSERT_BITS_HIGH(TMC2209_ACCESS_WRITE, tmc2209_reg_access(TMC2209_GSTAT));
    TEST_ASSERT_EQUAL(TMC2209_CLASS_VOLATILE, tmc2209_reg_class(TMC2209_GSTAT));
}

/* The mirror image: VACTUAL cannot be read back at all, yet only the firmware
   ever changes it, so the cache is the authoritative answer. */
static void test_vactual_is_owned_despite_being_write_only(void)
{
    TEST_ASSERT_BITS_LOW(TMC2209_ACCESS_READ, tmc2209_reg_access(TMC2209_VACTUAL));
    TEST_ASSERT_EQUAL(TMC2209_CLASS_OWNED, tmc2209_reg_class(TMC2209_VACTUAL));
}

/* Nothing writes PWMCONF: policy forbids the firmware, and the autotuner works
   on PWM_SCALE and PWM_AUTO instead. A value nobody changes is knowable after
   one read. */
static void test_constant_registers_are_the_ones_nobody_writes(void)
{
    const tmc2209_reg_t never_written[] = {
        TMC2209_FACTORY_CONF, TMC2209_OTP_READ, TMC2209_PWMCONF,
    };
    for (size_t i = 0; i < sizeof never_written / sizeof never_written[0]; i++) {
        TEST_ASSERT_EQUAL(TMC2209_CLASS_CONSTANT, tmc2209_reg_class(never_written[i]));
        TEST_ASSERT_BITS_HIGH(TMC2209_ACCESS_READ, tmc2209_reg_access(never_written[i]));
        TEST_ASSERT_BITS_LOW(TMC2209_ACCESS_WRITE, tmc2209_reg_access(never_written[i]));
    }
}

/* FACTORY_CONF is R/W driver-side, but writing it overwrites the factory
   oscillator trim and detunes every timing-derived quantity. The Python
   library did exactly that on every init. */
static void test_factory_conf_is_never_writable(void)
{
    TEST_ASSERT_BITS_LOW(TMC2209_ACCESS_WRITE, tmc2209_reg_access(TMC2209_FACTORY_CONF));
}

static void test_owned_registers_are_all_writable(void)
{
    for (int slot = 0; slot < TMC2209_REG_COUNT; slot++) {
        if (tmc2209_reg_class_at(slot) == TMC2209_CLASS_OWNED) {
            TEST_ASSERT_BITS_HIGH(TMC2209_ACCESS_WRITE, tmc2209_reg_access_at(slot));
        }
    }
}

/* Nothing outside the owned set may be written, which is what keeps a
   configuration batch from reaching a fault latch or a factory trim. */
static void test_nothing_unowned_is_writable_except_gstat(void)
{
    for (int slot = 0; slot < TMC2209_REG_COUNT; slot++) {
        if (tmc2209_reg_class_at(slot) == TMC2209_CLASS_OWNED) {
            continue;
        }
        if (tmc2209_reg_at(slot) == TMC2209_GSTAT) {
            continue;   /* write-1-to-clear, handled inside adopt() */
        }
        TEST_ASSERT_BITS_LOW(TMC2209_ACCESS_WRITE, tmc2209_reg_access_at(slot));
    }
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
        TEST_ASSERT_BITS_LOW(TMC2209_ACCESS_READ, access);
        TEST_ASSERT_BITS_HIGH(TMC2209_ACCESS_WRITE, access);
    }
    TEST_ASSERT_EQUAL_INT(8, (int)(sizeof write_only / sizeof write_only[0]));
}

/* Only two owned registers read back, which is the whole reason the cache
   cannot be repaired by interrogation and tmc2209_verify_config() is limited. */
static void test_only_gconf_and_chopconf_read_back(void)
{
    int readable = 0;
    for (int slot = 0; slot < TMC2209_REG_COUNT; slot++) {
        if (tmc2209_reg_class_at(slot) == TMC2209_CLASS_OWNED &&
            (tmc2209_reg_access_at(slot) & TMC2209_ACCESS_READ)) {
            readable++;
        }
    }
    TEST_ASSERT_EQUAL_INT(2, readable);
    TEST_ASSERT_BITS_HIGH(TMC2209_ACCESS_READ, tmc2209_reg_access(TMC2209_GCONF));
    TEST_ASSERT_BITS_HIGH(TMC2209_ACCESS_READ, tmc2209_reg_access(TMC2209_CHOPCONF));
}

static void test_names_are_present_and_unknown_is_marked(void)
{
    TEST_ASSERT_EQUAL_STRING("GCONF", tmc2209_reg_name(TMC2209_GCONF));
    TEST_ASSERT_EQUAL_STRING("DRV_STATUS", tmc2209_reg_name(TMC2209_DRV_STATUS));
    TEST_ASSERT_EQUAL_STRING("?", tmc2209_reg_name((tmc2209_reg_t)0x04));
}

/* ── Field codecs ───────────────────────────────────────────────────────── */

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

static void test_drv_status_decodes_fields(void)
{
    tmc2209_drv_status_t s = tmc2209_drv_status_decode(0x80170002u);
    TEST_ASSERT_TRUE(s.ot);
    TEST_ASSERT_FALSE(s.otpw);
    TEST_ASSERT_EQUAL_UINT8(0x17, s.cs_actual);
    TEST_ASSERT_TRUE(s.stst);
}

static void test_ioin_decodes_version(void)
{
    tmc2209_ioin_t i = tmc2209_ioin_decode(0x21000000u | (1u << 6));
    TEST_ASSERT_EQUAL_HEX8(TMC2209_IOIN_VERSION, i.version);
    TEST_ASSERT_TRUE(i.pdn_uart);
    TEST_ASSERT_FALSE(i.enn);
}

static void test_vactual_round_trips_signed(void)
{
    TEST_ASSERT_EQUAL_INT32(0,     tmc2209_vactual_decode(tmc2209_vactual_encode(0)));
    TEST_ASSERT_EQUAL_INT32(1000,  tmc2209_vactual_decode(tmc2209_vactual_encode(1000)));
    TEST_ASSERT_EQUAL_INT32(-1,    tmc2209_vactual_decode(tmc2209_vactual_encode(-1)));
    TEST_ASSERT_EQUAL_INT32(-1000, tmc2209_vactual_decode(tmc2209_vactual_encode(-1000)));

    /* The field is 24 bits, so encode must not leak sign bits into 31..24. */
    TEST_ASSERT_EQUAL_HEX32(0x00FFFFFFu, tmc2209_vactual_encode(-1));
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
    RUN_TEST(test_register_count_fits_the_validity_bitmap);
    RUN_TEST(test_every_register_is_classified);
    RUN_TEST(test_class_counts_are_ten_ten_three);
    RUN_TEST(test_otp_prog_stays_unreachable);

    RUN_TEST(test_volatile_registers_are_the_ones_hardware_writes);
    RUN_TEST(test_gstat_is_volatile_despite_being_writable);
    RUN_TEST(test_vactual_is_owned_despite_being_write_only);
    RUN_TEST(test_constant_registers_are_the_ones_nobody_writes);
    RUN_TEST(test_factory_conf_is_never_writable);
    RUN_TEST(test_owned_registers_are_all_writable);
    RUN_TEST(test_nothing_unowned_is_writable_except_gstat);
    RUN_TEST(test_write_only_registers_are_not_readable);
    RUN_TEST(test_only_gconf_and_chopconf_read_back);
    RUN_TEST(test_names_are_present_and_unknown_is_marked);

    RUN_TEST(test_chopconf_reset_decodes_to_256_microsteps_interpolated);
    RUN_TEST(test_ihold_irun_reset_decodes);
    RUN_TEST(test_gconf_round_trips);
    RUN_TEST(test_chopconf_round_trips);
    RUN_TEST(test_ihold_irun_and_coolconf_round_trip);
    RUN_TEST(test_mres_maps_to_microsteps);
    RUN_TEST(test_drv_status_decodes_fields);
    RUN_TEST(test_ioin_decodes_version);
    RUN_TEST(test_vactual_round_trips_signed);
    RUN_TEST(test_mscuract_sign_extends_both_phases);
    RUN_TEST(test_pwm_scale_and_auto_decode);
    RUN_TEST(test_gstat_round_trips);
}
