/*
 * test_rpc.c: the bridges, end to end, without a cable.
 *
 * A raw handler decodes arguments, makes one library call, and encodes what
 * came back. All three of those can be wrong independently, so the test drives
 * whole frames: build a REQ, run it through the real dispatch, and read the
 * REP the way the PC will.
 *
 * The paths worth the effort are the ones hardware will not produce on
 * request. A driver answers or it does not, and asking it to corrupt one CRC
 * is not a thing you can do. The mock does it on demand, which is what makes
 * the mapping from library error to wire status testable at all rather than
 * merely reviewed.
 */

#include <string.h>

#include "fake_devices.h"

unsigned fake_watchdog_arms(void);
#include "mock_tmc2209.h"
#include "rpc_dispatch.h"
#include "rpc_methods.h"
#include "rpc_api.h"
#include "rpc_proto.h"
#include "rpc_wire.h"
#include "tmc2209_frame.h"
#include "unity.h"

static mock_dev_t     g_mock;
static tmc2209_port_t g_port;
static tmc2209_bus_t  g_bus;
static tmc2209_t      g_dev;

/* A board with four pins, as test_lines.c uses. Levels persist, so a write is
   observable by the read after it. */
typedef struct {
    bool level[TMC2209_LINE_COUNT];
} fake_board_t;

static fake_board_t    g_board;
static tmc2209_lines_t g_lines;

static int board_read(void *ctx, tmc2209_line_t line)
{
    return ((fake_board_t *)ctx)->level[line] ? 1 : 0;
}

static int board_write(void *ctx, tmc2209_line_t line, bool level)
{
    ((fake_board_t *)ctx)->level[line] = level;
    return 0;
}

#define CFG_GCONF 0x000000C0u

static const tmc2209_regval_t k_config[] = {
    { TMC2209_GCONF,      CFG_GCONF   },
    { TMC2209_SLAVECONF,  0x00000200u },
    { TMC2209_IHOLD_IRUN, 0x00081810u },
    { TMC2209_TPOWERDOWN, 0x00000014u },
    { TMC2209_TPWMTHRS,   0x000001F4u },
    { TMC2209_TCOOLTHRS,  0x000003E8u },
    { TMC2209_VACTUAL,    0x00000000u },
    { TMC2209_SGTHRS,     0x00000050u },
    { TMC2209_COOLCONF,   0x00010203u },
    { TMC2209_CHOPCONF,   0x14010053u },
};

static void rpc_setup(bool with_lines)
{
    memset(&g_board, 0, sizeof(g_board));

    mock_init(&g_mock, &g_port, 0, true);
    g_bus.port       = &g_port;
    g_bus.timeout_ms = 10;
    g_bus.retries    = 0; /* one attempt, so an injected fault is the answer */

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_init(&g_dev, 0));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_attach_bus(&g_dev, &g_bus));

    if (with_lines) {
        g_lines.read  = board_read;
        g_lines.write = board_write;
        g_lines.ctx   = &g_board;
        g_lines.wired = TMC2209_LINES_ALL;
        TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_attach_lines(&g_dev, &g_lines));
    }

    tmc2209_t  *devs[]  = { &g_dev };
    const char *names[] = { "capstan" };
    fake_devices_set(devs, names, 1);

    rpc_reset_registry();
    rpc_register(RPC_NS_RAW, rpc_raw_methods, RPC_RAW_COUNT);
    rpc_register(RPC_NS_PASSTHROUGH, rpc_passthrough_methods, RPC_PT_COUNT);
}

/* ── Driving a call the way the link does ───────────────────────────────── */

static uint8_t g_req[RPC_MAX_FRAME];
static uint8_t g_rep[RPC_MAX_FRAME];

/*
 * Everything rpc_link.c's serve() does, minus the USB. Going through the real
 * framing means an argument this test encodes wrongly fails here rather than
 * on a bench, and it exercises the rewind that a failing handler depends on.
 */
static rpc_status_t call(uint8_t ns, uint8_t method,
                         const uint8_t *args, size_t args_len,
                         rpc_reader_t *out)
{
    rpc_writer_t w;
    rpc_frame_begin_req(&w, g_req, sizeof(g_req), 0x4242, ns, method);
    if (args_len > 0) {
        for (size_t i = 0; i < args_len; i++) {
            rpc_w_u8(&w, args[i]);
        }
    }
    size_t req_len = rpc_frame_finish(&w);
    TEST_ASSERT_GREATER_THAN(0, req_len);

    uint8_t      type;
    rpc_reader_t r;
    TEST_ASSERT_TRUE(rpc_frame_open(g_req, req_len, &type, &r));
    TEST_ASSERT_EQUAL_UINT8(RPC_FRAME_REQ, type);

    rpc_req_t req;
    TEST_ASSERT_TRUE(rpc_req_header(&r, &req));

    rpc_writer_t rep;
    rpc_frame_begin_rep(&rep, g_rep, sizeof(g_rep), req.id, RPC_OK);
    size_t mark = rep.len;

    rpc_status_t status = rpc_dispatch(&req, &r, &rep, mark);
    if (status != RPC_OK) {
        rpc_frame_set_status(&rep, status);
    }

    size_t rep_len = rpc_frame_finish(&rep);
    TEST_ASSERT_GREATER_THAN(0, rep_len);

    TEST_ASSERT_TRUE(rpc_frame_open(g_rep, rep_len, &type, out));
    TEST_ASSERT_EQUAL_UINT8(RPC_FRAME_REP, type);
    TEST_ASSERT_EQUAL_UINT16(0x4242, rpc_r_u16(out));

    uint8_t reported = rpc_r_u8(out);
    TEST_ASSERT_EQUAL_UINT8(status, reported);
    return status;
}

/* Argument builders, so a test reads as the call it is making. */
static size_t args_u8(uint8_t *buf, uint8_t a)
{
    buf[0] = a;
    return 1;
}

static size_t args_u8_u8(uint8_t *buf, uint8_t a, uint8_t b)
{
    buf[0] = a;
    buf[1] = b;
    return 2;
}

/* ── Dispatch ───────────────────────────────────────────────────────────── */

void test_rpc_unknown_namespace_and_method(void)
{
    rpc_setup(false);

    uint8_t      a[4];
    rpc_reader_t r;

    TEST_ASSERT_EQUAL(RPC_NO_METHOD, call(RPC_NS_SMART, 0, a, args_u8(a, 0), &r));
    TEST_ASSERT_EQUAL(RPC_NO_METHOD, call(RPC_NS_RAW, RPC_RAW_COUNT, a, args_u8(a, 0), &r));
}

void test_rpc_unknown_device_is_a_bad_argument(void)
{
    rpc_setup(false);

    uint8_t      a[4];
    rpc_reader_t r;

    TEST_ASSERT_EQUAL(RPC_ARG, call(RPC_NS_RAW, RPC_RAW_POLL, a,
                                    args_u8_u8(a, 7, TMC2209_IOIN), &r));
}

/* Both ways a frame can disagree with the method it names. */
void test_rpc_malformed_arguments_are_bad_frames(void)
{
    rpc_setup(false);

    uint8_t      a[8];
    rpc_reader_t r;

    /* One argument short: poll wants a device and a register. */
    TEST_ASSERT_EQUAL(RPC_BAD_FRAME, call(RPC_NS_RAW, RPC_RAW_POLL, a,
                                          args_u8(a, 0), &r));

    /* One argument too many. Left over means the ends disagree about the
       method, which is worth catching now rather than at the field that
       eventually matters. */
    a[0] = 0;
    a[1] = TMC2209_IOIN;
    a[2] = 0xFF;
    TEST_ASSERT_EQUAL(RPC_BAD_FRAME, call(RPC_NS_RAW, RPC_RAW_POLL, a, 3, &r));
}

/* ── raw, the happy path ────────────────────────────────────────────────── */

void test_rpc_poll_returns_what_the_device_holds(void)
{
    rpc_setup(false);
    mock_set_reg(&g_mock, TMC2209_IOIN, 0x21000041u);

    uint8_t      a[4];
    rpc_reader_t r;

    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_RAW, RPC_RAW_POLL, a,
                                   args_u8_u8(a, 0, TMC2209_IOIN), &r));
    TEST_ASSERT_EQUAL_HEX32(0x21000041u, rpc_r_u32(&r));
    TEST_ASSERT_TRUE(rpc_r_done(&r));
}

void test_rpc_read_serves_the_cache_and_refuses_an_empty_slot(void)
{
    rpc_setup(false);

    uint8_t      a[4];
    rpc_reader_t r;

    /* Nothing has been written, so nothing may be reported. */
    TEST_ASSERT_EQUAL(RPC_INVALID_SLOT, call(RPC_NS_RAW, RPC_RAW_READ, a,
                                             args_u8_u8(a, 0, TMC2209_GCONF), &r));

    TEST_ASSERT_EQUAL(TMC2209_OK,
                      tmc2209_bringup(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));

    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_RAW, RPC_RAW_READ, a,
                                   args_u8_u8(a, 0, TMC2209_GCONF), &r));
    TEST_ASSERT_EQUAL_HEX32(CFG_GCONF, rpc_r_u32(&r));
}

void test_rpc_write_batch_lands_on_the_device(void)
{
    rpc_setup(false);
    TEST_ASSERT_EQUAL(TMC2209_OK,
                      tmc2209_bringup(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));

    uint8_t      a[32];
    rpc_writer_t w;
    rpc_w_init(&w, a, sizeof(a));
    rpc_w_u8(&w, 0);
    rpc_w_u16(&w, 2);
    rpc_w_u8(&w, TMC2209_SGTHRS);
    rpc_w_u32(&w, 0x33u);
    rpc_w_u8(&w, TMC2209_TPOWERDOWN);
    rpc_w_u32(&w, 0x44u);

    rpc_reader_t r;
    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_RAW, RPC_RAW_WRITE, a, w.len, &r));

    TEST_ASSERT_EQUAL_HEX32(0x33u, mock_reg(&g_mock, TMC2209_SGTHRS));
    TEST_ASSERT_EQUAL_HEX32(0x44u, mock_reg(&g_mock, TMC2209_TPOWERDOWN));
}

void test_rpc_poll_health_reports_the_conditions(void)
{
    rpc_setup(false);

    uint8_t      a[4];
    rpc_reader_t r;

    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_RAW, RPC_RAW_POLL_HEALTH, a,
                                   args_u8(a, 0), &r));

    /* The mock powers on with GSTAT.reset set, as a real part does. */
    uint32_t conditions = rpc_r_u32(&r);
    TEST_ASSERT_BITS_HIGH(TMC2209_DRIVER_RESET, conditions);
}

void test_rpc_verify_config_reports_agreement_as_a_value(void)
{
    rpc_setup(false);
    TEST_ASSERT_EQUAL(TMC2209_OK,
                      tmc2209_bringup(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));

    uint8_t      a[4];
    rpc_reader_t r;

    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_RAW, RPC_RAW_VERIFY_CONFIG, a,
                                   args_u8(a, 0), &r));
    TEST_ASSERT_TRUE(rpc_r_bool(&r));
    TEST_ASSERT_EQUAL_HEX32(0, rpc_r_u32(&r));

    /* Disagree behind the library's back. The call still succeeds, because
       finding a mismatch is what it is for; the mask is the answer. */
    mock_set_reg(&g_mock, TMC2209_GCONF, CFG_GCONF ^ 0x40u);

    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_RAW, RPC_RAW_VERIFY_CONFIG, a,
                                   args_u8(a, 0), &r));
    TEST_ASSERT_FALSE(rpc_r_bool(&r));
    TEST_ASSERT_NOT_EQUAL(0, rpc_r_u32(&r));
}

/* ── raw, the paths hardware will not give you ──────────────────────────── */

void test_rpc_transport_faults_reach_the_wire_as_themselves(void)
{
    uint8_t      a[4];
    rpc_reader_t r;

    rpc_setup(false);
    g_mock.fail_crc = 1;
    TEST_ASSERT_EQUAL(RPC_CRC, call(RPC_NS_RAW, RPC_RAW_POLL, a,
                                    args_u8_u8(a, 0, TMC2209_IOIN), &r));
    TEST_ASSERT_TRUE(rpc_r_done(&r)); /* an error carries nothing */

    rpc_setup(false);
    g_mock.drop_reply = 1;
    TEST_ASSERT_EQUAL(RPC_RX_TIMEOUT, call(RPC_NS_RAW, RPC_RAW_POLL, a,
                                           args_u8_u8(a, 0, TMC2209_IOIN), &r));

    rpc_setup(false);
    g_mock.wrong_reg = 1;
    TEST_ASSERT_EQUAL(RPC_REG, call(RPC_NS_RAW, RPC_RAW_POLL, a,
                                    args_u8_u8(a, 0, TMC2209_IOIN), &r));

    rpc_setup(false);
    g_mock.corrupt_echo = 1;
    TEST_ASSERT_EQUAL(RPC_ECHO, call(RPC_NS_RAW, RPC_RAW_POLL, a,
                                     args_u8_u8(a, 0, TMC2209_IOIN), &r));
}

void test_rpc_an_unconfirmed_write_is_not_reported_as_a_write(void)
{
    rpc_setup(false);
    g_mock.freeze_ifcnt = 1;

    uint8_t      a[32];
    rpc_writer_t w;
    rpc_w_init(&w, a, sizeof(a));
    rpc_w_u8(&w, 0);
    rpc_w_u16(&w, 1);
    rpc_w_u8(&w, TMC2209_SGTHRS);
    rpc_w_u32(&w, 0x55u);

    rpc_reader_t r;
    TEST_ASSERT_EQUAL(RPC_NO_ACK, call(RPC_NS_RAW, RPC_RAW_WRITE, a, w.len, &r));
}

static size_t move_args(uint8_t *buf, size_t cap, uint32_t deadline_ms)
{
    rpc_writer_t w;
    rpc_w_init(&w, buf, cap);
    rpc_w_u8(&w, 0);
    rpc_w_bool(&w, true);  /* dir level */
    rpc_w_bool(&w, false); /* the shaft bit the caller counts on */
    rpc_w_u32(&w, 100);  /* pulses */
    rpc_w_u32(&w, 200);  /* pullin */
    rpc_w_u32(&w, 1000); /* cruise */
    rpc_w_u32(&w, 5000); /* accel */
    rpc_w_u32(&w, deadline_ms);
    return w.len;
}

void test_rpc_a_missing_backend_is_not_a_failure_to_move(void)
{
    rpc_setup(true);

    uint8_t a[32];
    size_t  n = move_args(a, sizeof(a), 0);

    rpc_reader_t r;
    TEST_ASSERT_EQUAL(RPC_NO_BACKEND, call(RPC_NS_RAW, RPC_RAW_MOVE, a, n, &r));
}

/*
 * A refused move must not arm the deadline. Arming one for a run that never
 * started would have the watchdog halt and disable a driver nobody touched,
 * which is the failure mode a safety mechanism can least afford.
 */
void test_rpc_a_refused_move_arms_nothing(void)
{
    rpc_setup(true);

    unsigned before = fake_watchdog_arms();

    uint8_t a[32];
    size_t  n = move_args(a, sizeof(a), 0);

    rpc_reader_t r;
    TEST_ASSERT_EQUAL(RPC_NO_BACKEND, call(RPC_NS_RAW, RPC_RAW_MOVE, a, n, &r));
    TEST_ASSERT_EQUAL_UINT(before, fake_watchdog_arms());
}

/* ── Lines ──────────────────────────────────────────────────────────────── */

void test_rpc_lines_drive_and_read_back(void)
{
    rpc_setup(true);

    uint8_t      a[8];
    rpc_reader_t r;

    a[0] = 0;
    a[1] = TMC2209_LINE_DIR;
    a[2] = 1;
    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_RAW, RPC_RAW_LINE_WRITE, a, 3, &r));
    TEST_ASSERT_TRUE(g_board.level[TMC2209_LINE_DIR]);

    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_RAW, RPC_RAW_LINE_READ, a,
                                   args_u8_u8(a, 0, TMC2209_LINE_DIR), &r));
    TEST_ASSERT_TRUE(rpc_r_bool(&r));
}

/* ENN is active low, so enable() and the level disagree by construction. A
   test that asked only one of them could not tell correct from inverted. */
void test_rpc_enable_applies_the_parts_polarity(void)
{
    rpc_setup(true);

    uint8_t      a[8];
    rpc_reader_t r;

    a[0] = 0;
    a[1] = 1;
    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_RAW, RPC_RAW_ENABLE, a, 2, &r));
    TEST_ASSERT_FALSE(g_board.level[TMC2209_LINE_ENN]);

    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_RAW, RPC_RAW_IS_ENABLED, a,
                                   args_u8(a, 0), &r));
    TEST_ASSERT_TRUE(rpc_r_bool(&r));
}

void test_rpc_an_unwired_line_is_refused_not_guessed(void)
{
    rpc_setup(true);
    g_lines.wired = TMC2209_LINES_ALL & (uint8_t)~TMC2209_LINE_BIT(TMC2209_LINE_DIAG);

    uint8_t      a[8];
    rpc_reader_t r;

    TEST_ASSERT_EQUAL(RPC_UNWIRED, call(RPC_NS_RAW, RPC_RAW_LINE_READ, a,
                                        args_u8_u8(a, 0, TMC2209_LINE_DIAG), &r));
}

/* ── Passthrough ────────────────────────────────────────────────────────── */

static size_t read_request(uint8_t *buf, uint8_t dev_idx, uint8_t reply_len,
                           uint8_t addr, tmc2209_reg_t reg)
{
    uint8_t datagram[TMC2209_READ_REQ_LEN];
    tmc2209_frame_read_request(datagram, addr, (uint8_t)reg);

    rpc_writer_t w;
    rpc_w_init(&w, buf, 32);
    rpc_w_u8(&w, dev_idx);
    rpc_w_u8(&w, reply_len);
    rpc_w_bytes(&w, datagram, sizeof(datagram));

    return w.len;
}

void test_rpc_passthrough_hands_back_the_reply_undecoded(void)
{
    rpc_setup(false);
    mock_set_reg(&g_mock, TMC2209_IOIN, 0x21000041u);

    uint8_t a[32];
    size_t  n = read_request(a, 0, TMC2209_REPLY_LEN, 0, TMC2209_IOIN);

    rpc_reader_t r;
    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_PASSTHROUGH, RPC_PT_SEND, a, n, &r));

    /* The frame succeeded; what the wire did is a value. */
    TEST_ASSERT_EQUAL_UINT8(RPC_OK, rpc_r_u8(&r));

    size_t         len   = 0;
    const uint8_t *bytes = rpc_r_bytes(&r, &len);
    TEST_ASSERT_EQUAL_size_t(TMC2209_REPLY_LEN, len);

    /* Undecoded, so the test decodes it the way the PC will. */
    uint32_t      value = 0;
    tmc2209_err_t err   = tmc2209_frame_parse_reply(bytes, TMC2209_IOIN, &value);
    TEST_ASSERT_EQUAL(TMC2209_OK, err);
    TEST_ASSERT_EQUAL_HEX32(0x21000041u, value);
}

/*
 * Silence is an answer here, not a failure. The reply still arrives with the
 * shape a client expects, so a diagnostic can tell "nothing came back" from
 * "the call was malformed" without a special case.
 */
void test_rpc_passthrough_reports_silence_without_failing_the_call(void)
{
    rpc_setup(false);
    g_mock.drop_reply = 1;

    uint8_t a[32];
    size_t  n = read_request(a, 0, TMC2209_REPLY_LEN, 0, TMC2209_IOIN);

    rpc_reader_t r;
    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_PASSTHROUGH, RPC_PT_SEND, a, n, &r));
    TEST_ASSERT_EQUAL_UINT8(RPC_RX_TIMEOUT, rpc_r_u8(&r));

    size_t len = 1;
    (void)rpc_r_bytes(&r, &len);
    TEST_ASSERT_EQUAL_size_t(0, len);
    TEST_ASSERT_TRUE(rpc_r_done(&r));
}

/*
 * The cache rule that follows from who assembled the bytes. A datagram the
 * library did not build may have written anything, so the owned slots stop
 * being believable. A four-byte read request is the exception, because it
 * cannot have changed the driver.
 */
void test_rpc_passthrough_writes_void_the_cache_and_reads_do_not(void)
{
    rpc_setup(false);
    TEST_ASSERT_EQUAL(TMC2209_OK,
                      tmc2209_bringup(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));
    TEST_ASSERT_TRUE(tmc2209_all_owned_valid(&g_dev));

    uint8_t      a[32];
    rpc_reader_t r;

    size_t n = read_request(a, 0, TMC2209_REPLY_LEN, 0, TMC2209_IOIN);
    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_PASSTHROUGH, RPC_PT_SEND, a, n, &r));
    TEST_ASSERT_TRUE(tmc2209_all_owned_valid(&g_dev));

    uint8_t datagram[TMC2209_WRITE_LEN];
    tmc2209_frame_write(datagram, 0, TMC2209_SGTHRS, 0x11u);

    rpc_writer_t w;
    rpc_w_init(&w, a, sizeof(a));
    rpc_w_u8(&w, 0);
    rpc_w_u8(&w, 0); /* a write has no reply */
    rpc_w_bytes(&w, datagram, sizeof(datagram));

    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_PASSTHROUGH, RPC_PT_SEND, a, w.len, &r));
    TEST_ASSERT_FALSE(tmc2209_all_owned_valid(&g_dev));
}

void test_rpc_passthrough_refuses_an_oversized_datagram(void)
{
    rpc_setup(false);

    uint8_t      a[64];
    rpc_writer_t w;
    rpc_w_init(&w, a, sizeof(a));
    rpc_w_u8(&w, 0);
    rpc_w_u8(&w, 0);
    rpc_w_u16(&w, 40); /* claims 40 bytes, over the part's longest datagram */
    for (int i = 0; i < 40; i++) {
        rpc_w_u8(&w, 0xAA);
    }

    rpc_reader_t r;
    TEST_ASSERT_EQUAL(RPC_ARG, call(RPC_NS_PASSTHROUGH, RPC_PT_SEND, a, w.len, &r));
}

void run_rpc_tests(void)
{
    RUN_TEST(test_rpc_unknown_namespace_and_method);
    RUN_TEST(test_rpc_unknown_device_is_a_bad_argument);
    RUN_TEST(test_rpc_malformed_arguments_are_bad_frames);
    RUN_TEST(test_rpc_poll_returns_what_the_device_holds);
    RUN_TEST(test_rpc_read_serves_the_cache_and_refuses_an_empty_slot);
    RUN_TEST(test_rpc_write_batch_lands_on_the_device);
    RUN_TEST(test_rpc_poll_health_reports_the_conditions);
    RUN_TEST(test_rpc_verify_config_reports_agreement_as_a_value);
    RUN_TEST(test_rpc_transport_faults_reach_the_wire_as_themselves);
    RUN_TEST(test_rpc_an_unconfirmed_write_is_not_reported_as_a_write);
    RUN_TEST(test_rpc_a_missing_backend_is_not_a_failure_to_move);
    RUN_TEST(test_rpc_a_refused_move_arms_nothing);
    RUN_TEST(test_rpc_lines_drive_and_read_back);
    RUN_TEST(test_rpc_enable_applies_the_parts_polarity);
    RUN_TEST(test_rpc_an_unwired_line_is_refused_not_guessed);
    RUN_TEST(test_rpc_passthrough_hands_back_the_reply_undecoded);
    RUN_TEST(test_rpc_passthrough_reports_silence_without_failing_the_call);
    RUN_TEST(test_rpc_passthrough_writes_void_the_cache_and_reads_do_not);
    RUN_TEST(test_rpc_passthrough_refuses_an_oversized_datagram);
}
