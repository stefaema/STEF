/*
 * test_rpc.c: the bridges, end to end, without a cable.
 *
 * A raw handler reads its arguments, makes one library call, and writes what
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

#include <stddef.h>
#include <string.h>

#include "fake_devices.h"
#include "fw_api.h"
#include "mock_tmc2209.h"
#include "rpc_dispatch.h"
#include "rpc_frame.h"
#include "rpc_methods.h"
#include "rpc_proto.h"
#include "tmc2209_frame.h"
#include "unity.h"

static mock_dev_t     g_mock;
static tmc2209_uart_t g_uart;
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
    return (int)((fake_board_t *)ctx)->level[line];
}

static int board_write(void *ctx, tmc2209_line_t line, bool level)
{
    ((fake_board_t *)ctx)->level[line] = level;
    return 0;
}

#define CFG_GCONF 0x000000C0U

static const tmc2209_regval_t k_config[] = {
    { TMC2209_GCONF,      CFG_GCONF   },
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

static void rpc_setup(bool with_lines)
{
    memset(&g_board, 0, sizeof(g_board));

    mock_init(&g_mock, &g_uart, 0, true);
    g_uart.timeout_ms = 10;
    g_uart.retries    = 0; /* one attempt, so an injected fault is the answer */

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_init(&g_dev, 0));
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_attach_uart(&g_dev, &g_uart));

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
    rpc_register(RPC_NS_RELAY, rpc_relay_methods, RPC_RELAY_COUNT);
}

/* ── Driving a call the way the link does ───────────────────────────────── */

static rpc_buf_t g_req;
static rpc_buf_t g_rep;

/* What the reply carried, so a test reads its fields as the struct they are. */
static const void *g_ret;
static size_t      g_ret_len;

/*
 * Everything rpc_link.c's serve() does, minus the USB. Going through the real
 * framing means an argument this test lays out wrongly fails here rather than
 * on a bench, and it exercises dispatch's length check rather than stepping
 * around it.
 */
static rpc_status_t call(uint8_t ns, uint8_t method, const void *args, size_t args_len)
{
    g_ret     = NULL;
    g_ret_len = 0;

    if (args_len > 0) {
        memcpy(rpc_payload(&g_req), args, args_len);
    }

    size_t req_len = rpc_frame_seal_req(&g_req, 0x4242, ns, method, args_len);
    TEST_ASSERT_GREATER_THAN(0, req_len);

    rpc_view_t rv;
    TEST_ASSERT_TRUE(rpc_frame_open(&g_req, req_len, &rv));
    TEST_ASSERT_EQUAL_UINT8(RPC_FRAME_REQ, rv.type);

    const rpc_req_hdr_t *req = rv.hdr;

    size_t       ret_len = 0;
    rpc_status_t status  = rpc_dispatch(req->ns, req->method, rv.payload, rv.payload_len,
                                        rpc_payload(&g_rep), &ret_len);

    size_t rep_len = rpc_frame_seal_rep(&g_rep, req->id, status, ret_len);
    TEST_ASSERT_GREATER_THAN(0, rep_len);

    rpc_view_t pv;
    TEST_ASSERT_TRUE(rpc_frame_open(&g_rep, rep_len, &pv));
    TEST_ASSERT_EQUAL_UINT8(RPC_FRAME_REP, pv.type);

    const rpc_rep_hdr_t *rep = pv.hdr;
    TEST_ASSERT_EQUAL_UINT16(0x4242, rep->id);
    TEST_ASSERT_EQUAL_UINT8(status, rep->status);

    g_ret     = pv.payload;
    g_ret_len = pv.payload_len;
    return status;
}

/** The reply's payload as the struct the method promises, size checked. */
#define RET(type) (TEST_ASSERT_EQUAL_size_t(sizeof(type), g_ret_len), (const type *)g_ret)

/** A device index, which is most of raw's argument list. */
static rpc_dev_args dev_args(uint8_t idx)
{
    rpc_dev_args a = { .idx = idx };
    return a;
}

/* ── Dispatch ───────────────────────────────────────────────────────────── */

void test_rpc_unknown_namespace_and_method(void)
{
    rpc_setup(false);

    rpc_dev_args a = dev_args(0);

    TEST_ASSERT_EQUAL(RPC_NO_METHOD, call(RPC_NS_FILM, 0, &a, sizeof(a)));
    TEST_ASSERT_EQUAL(RPC_NO_METHOD, call(RPC_NS_RAW, RPC_RAW_COUNT, &a, sizeof(a)));
}

void test_rpc_unknown_device_is_a_bad_argument(void)
{
    rpc_setup(false);

    rpc_raw_poll_args a = { .idx = 7, .reg = TMC2209_IOIN };
    TEST_ASSERT_EQUAL(RPC_ARG, call(RPC_NS_RAW, RPC_RAW_POLL, &a, sizeof(a)));
}

/*
 * Both ways a frame can disagree with the method it names. Dispatch checks the
 * length against the table, so neither a short payload nor a long one reaches
 * a handler, and the handler never learns that either was possible.
 */
void test_rpc_a_payload_of_the_wrong_length_is_a_bad_frame(void)
{
    rpc_setup(false);

    rpc_raw_poll_args a = { .idx = 0, .reg = TMC2209_IOIN };

    TEST_ASSERT_EQUAL(RPC_BAD_FRAME, call(RPC_NS_RAW, RPC_RAW_POLL, &a, sizeof(a) - 1U));
    TEST_ASSERT_EQUAL(RPC_BAD_FRAME, call(RPC_NS_RAW, RPC_RAW_POLL, &a, sizeof(a) + 1U));
    TEST_ASSERT_EQUAL(RPC_BAD_FRAME, call(RPC_NS_RAW, RPC_RAW_POLL, &a, 0));
}

/* A failing status carries nothing, so a client never reads return values that
 * describe a call that did not happen. */
void test_rpc_a_failing_call_carries_no_payload(void)
{
    rpc_setup(false);

    rpc_raw_poll_args a = { .idx = 7, .reg = TMC2209_IOIN };

    TEST_ASSERT_EQUAL(RPC_ARG, call(RPC_NS_RAW, RPC_RAW_POLL, &a, sizeof(a)));
    TEST_ASSERT_EQUAL_size_t(0, g_ret_len);
}

/* ── raw, the happy path ────────────────────────────────────────────────── */

void test_rpc_poll_returns_what_the_device_holds(void)
{
    rpc_setup(false);
    mock_set_reg(&g_mock, TMC2209_IOIN, 0x21000041U);

    rpc_raw_poll_args a = { .idx = 0, .reg = TMC2209_IOIN };

    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_RAW, RPC_RAW_POLL, &a, sizeof(a)));
    TEST_ASSERT_EQUAL_HEX32(0x21000041U, RET(rpc_raw_poll_ret)->value);
}

void test_rpc_read_serves_the_cache_and_refuses_an_empty_slot(void)
{
    rpc_setup(false);

    rpc_raw_read_args a = { .idx = 0, .reg = TMC2209_GCONF };

    /* Nothing has been written, so nothing may be reported. */
    TEST_ASSERT_EQUAL(RPC_INVALID_SLOT, call(RPC_NS_RAW, RPC_RAW_READ, &a, sizeof(a)));

    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_bringup(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));

    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_RAW, RPC_RAW_READ, &a, sizeof(a)));
    TEST_ASSERT_EQUAL_HEX32(CFG_GCONF, RET(rpc_raw_read_ret)->value);
}

/* A batch is a head and a flexible tail, so its storage is the head plus as
   many elements as the call names. */
typedef union {
    rpc_raw_write_args w;
    uint8_t            bytes[sizeof(rpc_raw_write_args) + (4U * sizeof(rpc_op_t))];
} write_args_t;

static size_t write_args(write_args_t *a, uint8_t idx, const rpc_op_t *ops, uint32_t n)
{
    memset(a, 0, sizeof(*a));
    a->w.idx   = idx;
    a->w.count = n;

    for (uint32_t i = 0; i < n; i++) {
        a->w.ops[i] = ops[i];
    }

    return sizeof(rpc_raw_write_args) + (n * sizeof(rpc_op_t));
}

void test_rpc_write_batch_lands_on_the_device(void)
{
    rpc_setup(false);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_bringup(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));

    const rpc_op_t ops[] = {
        { .reg = TMC2209_SGTHRS,     .value = 0x33U },
        { .reg = TMC2209_TPOWERDOWN, .value = 0x44U },
    };

    write_args_t a;
    size_t       n = write_args(&a, 0, ops, 2);

    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_RAW, RPC_RAW_WRITE, &a, n));

    TEST_ASSERT_EQUAL_HEX32(0x33U, mock_reg(&g_mock, TMC2209_SGTHRS));
    TEST_ASSERT_EQUAL_HEX32(0x44U, mock_reg(&g_mock, TMC2209_TPOWERDOWN));
}

/* The count is inside the payload, so dispatch can only check that a head
 * arrived. The handler is what reconciles the two, and this is that check. */
void test_rpc_a_batch_that_lies_about_its_count_is_a_bad_frame(void)
{
    rpc_setup(false);

    const rpc_op_t ops[] = {
        { .reg = TMC2209_SGTHRS, .value = 0x33U }
    };

    write_args_t a;
    size_t       n = write_args(&a, 0, ops, 1);

    a.w.count = 3; /* claims three, sent one */
    TEST_ASSERT_EQUAL(RPC_BAD_FRAME, call(RPC_NS_RAW, RPC_RAW_WRITE, &a, n));

    a.w.count = 0; /* a batch of nothing is not a batch */
    TEST_ASSERT_EQUAL(RPC_BAD_FRAME, call(RPC_NS_RAW, RPC_RAW_WRITE, &a, n));

    a.w.count = RPC_MAX_OPS + 1U;
    TEST_ASSERT_EQUAL(RPC_BAD_FRAME, call(RPC_NS_RAW, RPC_RAW_WRITE, &a, n));
}

void test_rpc_poll_health_reports_the_conditions(void)
{
    rpc_setup(false);

    rpc_dev_args a = dev_args(0);

    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_RAW, RPC_RAW_POLL_HEALTH, &a, sizeof(a)));

    /* The mock powers on with GSTAT.reset set, as a real part does. */
    TEST_ASSERT_BITS_HIGH(TMC2209_DRIVER_RESET, RET(rpc_raw_poll_health_ret)->conditions);
}

void test_rpc_verify_config_reports_agreement_as_a_value(void)
{
    rpc_setup(false);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_bringup(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));

    rpc_dev_args a = dev_args(0);

    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_RAW, RPC_RAW_VERIFY_CONFIG, &a, sizeof(a)));
    TEST_ASSERT_EQUAL_UINT8(1, RET(rpc_raw_verify_config_ret)->agrees);
    TEST_ASSERT_EQUAL_HEX32(0, RET(rpc_raw_verify_config_ret)->mismatched);

    /* Disagree behind the library's back. The call still succeeds, because
       finding a mismatch is what it is for; the mask is the answer. */
    mock_set_reg(&g_mock, TMC2209_GCONF, CFG_GCONF ^ 0x40U);

    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_RAW, RPC_RAW_VERIFY_CONFIG, &a, sizeof(a)));
    TEST_ASSERT_EQUAL_UINT8(0, RET(rpc_raw_verify_config_ret)->agrees);
    TEST_ASSERT_NOT_EQUAL(0, RET(rpc_raw_verify_config_ret)->mismatched);
}

/* ── raw, the paths hardware will not give you ──────────────────────────── */

void test_rpc_transport_faults_reach_the_wire_as_themselves(void)
{
    rpc_raw_poll_args a = { .idx = 0, .reg = TMC2209_IOIN };

    rpc_setup(false);
    g_mock.fail_crc = 1;
    TEST_ASSERT_EQUAL(RPC_CRC, call(RPC_NS_RAW, RPC_RAW_POLL, &a, sizeof(a)));
    TEST_ASSERT_EQUAL_size_t(0, g_ret_len); /* an error carries nothing */

    rpc_setup(false);
    g_mock.drop_reply = 1;
    TEST_ASSERT_EQUAL(RPC_RX_TIMEOUT, call(RPC_NS_RAW, RPC_RAW_POLL, &a, sizeof(a)));

    rpc_setup(false);
    g_mock.wrong_reg = 1;
    TEST_ASSERT_EQUAL(RPC_REG, call(RPC_NS_RAW, RPC_RAW_POLL, &a, sizeof(a)));

    rpc_setup(false);
    g_mock.corrupt_echo = 1;
    TEST_ASSERT_EQUAL(RPC_ECHO, call(RPC_NS_RAW, RPC_RAW_POLL, &a, sizeof(a)));
}

void test_rpc_an_unconfirmed_write_is_not_reported_as_a_write(void)
{
    rpc_setup(false);
    g_mock.freeze_ifcnt = 1;

    const rpc_op_t ops[] = {
        { .reg = TMC2209_SGTHRS, .value = 0x55U }
    };

    write_args_t a;
    size_t       n = write_args(&a, 0, ops, 1);

    TEST_ASSERT_EQUAL(RPC_NO_ACK, call(RPC_NS_RAW, RPC_RAW_WRITE, &a, n));
}

static rpc_raw_move_args move_args(void)
{
    rpc_raw_move_args m = {
        .idx         = 0,
        .dir         = 1, /* the level to drive on DIR */
        .shaft       = 0, /* the shaft bit the caller counts on */
        .pulses      = 100,
        .pullin_pps  = 200,
        .cruise_pps  = 1000,
        .accel_pps_s = 5000,
    };
    return m;
}

void test_rpc_a_missing_backend_is_not_a_failure_to_move(void)
{
    rpc_setup(true);

    rpc_raw_move_args m = move_args();
    TEST_ASSERT_EQUAL(RPC_NO_BACKEND, call(RPC_NS_RAW, RPC_RAW_MOVE, &m, sizeof(m)));
}

/* ── Lines ──────────────────────────────────────────────────────────────── */

void test_rpc_lines_drive_and_read_back(void)
{
    rpc_setup(true);

    rpc_raw_line_write_args w = { .idx = 0, .line = TMC2209_LINE_DIR, .level = 1 };
    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_RAW, RPC_RAW_LINE_WRITE, &w, sizeof(w)));
    TEST_ASSERT_TRUE(g_board.level[TMC2209_LINE_DIR]);

    rpc_raw_line_read_args r = { .idx = 0, .line = TMC2209_LINE_DIR };
    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_RAW, RPC_RAW_LINE_READ, &r, sizeof(r)));
    TEST_ASSERT_EQUAL_UINT8(1, RET(rpc_raw_line_read_ret)->level);
}

/* ENN is active low, so enable() and the level disagree by construction. A
   test that asked only one of them could not tell correct from inverted. */
void test_rpc_enable_applies_the_parts_polarity(void)
{
    rpc_setup(true);

    rpc_raw_enable_args e = { .idx = 0, .on = 1 };
    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_RAW, RPC_RAW_ENABLE, &e, sizeof(e)));
    TEST_ASSERT_FALSE(g_board.level[TMC2209_LINE_ENN]);

    rpc_dev_args a = dev_args(0);
    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_RAW, RPC_RAW_IS_ENABLED, &a, sizeof(a)));
    TEST_ASSERT_EQUAL_UINT8(1, RET(rpc_raw_is_enabled_ret)->on);
}

void test_rpc_an_unwired_line_is_refused_not_guessed(void)
{
    rpc_setup(true);
    g_lines.wired = TMC2209_LINES_ALL & (uint8_t)~TMC2209_LINE_BIT(TMC2209_LINE_DIAG);

    rpc_raw_line_read_args r = { .idx = 0, .line = TMC2209_LINE_DIAG };
    TEST_ASSERT_EQUAL(RPC_UNWIRED, call(RPC_NS_RAW, RPC_RAW_LINE_READ, &r, sizeof(r)));
}

/* ── Relay ──────────────────────────────────────────────────────────────── */

typedef union {
    rpc_relay_send_args s;
    uint8_t             bytes[sizeof(rpc_relay_send_args) + RPC_RELAY_MAX_BYTES];
} relay_args_t;

static size_t relay_args(relay_args_t *a, uint8_t idx, uint8_t reply_len, const uint8_t *tx,
                         uint8_t count)
{
    memset(a, 0, sizeof(*a));
    a->s.idx       = idx;
    a->s.reply_len = reply_len;
    a->s.count     = count;
    memcpy(a->s.tx, tx, count);

    return sizeof(rpc_relay_send_args) + count;
}

static size_t read_request(relay_args_t *a, uint8_t dev_idx, uint8_t reply_len, uint8_t addr,
                           tmc2209_reg_t reg)
{
    uint8_t datagram[TMC2209_READ_REQ_LEN];
    tmc2209_frame_read_request(datagram, addr, (uint8_t)reg);

    return relay_args(a, dev_idx, reply_len, datagram, sizeof(datagram));
}

void test_rpc_relay_hands_back_the_reply_undecoded(void)
{
    rpc_setup(false);
    mock_set_reg(&g_mock, TMC2209_IOIN, 0x21000041U);

    relay_args_t a;
    size_t       n = read_request(&a, 0, TMC2209_REPLY_LEN, 0, TMC2209_IOIN);

    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_RELAY, RPC_RELAY_SEND, &a, n));

    /* The frame succeeded; what the wire did is a value. */
    const rpc_relay_send_ret *out = g_ret;
    TEST_ASSERT_EQUAL_UINT8(RPC_OK, out->outcome);
    TEST_ASSERT_EQUAL_UINT8(TMC2209_REPLY_LEN, out->count);
    TEST_ASSERT_EQUAL_size_t(offsetof(rpc_relay_send_ret, rx) + TMC2209_REPLY_LEN, g_ret_len);

    /* Undecoded, so the test decodes it the way the PC will. */
    uint32_t      value = 0;
    tmc2209_err_t err   = tmc2209_frame_parse_reply(out->rx, TMC2209_IOIN, &value);
    TEST_ASSERT_EQUAL(TMC2209_OK, err);
    TEST_ASSERT_EQUAL_HEX32(0x21000041U, value);
}

/*
 * Silence is an answer here, not a failure. The reply still arrives with the
 * shape a client expects, so a diagnostic can tell "nothing came back" from
 * "the call was malformed" without a special case.
 */
void test_rpc_relay_reports_silence_without_failing_the_call(void)
{
    rpc_setup(false);
    g_mock.drop_reply = 1;

    relay_args_t a;
    size_t       n = read_request(&a, 0, TMC2209_REPLY_LEN, 0, TMC2209_IOIN);

    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_RELAY, RPC_RELAY_SEND, &a, n));

    const rpc_relay_send_ret *out = g_ret;
    TEST_ASSERT_EQUAL_UINT8(RPC_RX_TIMEOUT, out->outcome);
    TEST_ASSERT_EQUAL_UINT8(0, out->count);
    TEST_ASSERT_EQUAL_size_t(offsetof(rpc_relay_send_ret, rx), g_ret_len);
}

/*
 * The cache rule that follows from who assembled the bytes. A datagram the
 * library did not build may have written anything, so the owned slots stop
 * being believable. A four-byte read request is the exception, because it
 * cannot have changed the driver.
 */
void test_rpc_relay_writes_void_the_cache_and_reads_do_not(void)
{
    rpc_setup(false);
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_bringup(&g_dev, k_config, TMC2209_NELEM(k_config), NULL));
    TEST_ASSERT_TRUE(tmc2209_all_owned_valid(&g_dev));

    relay_args_t a;
    size_t       n = read_request(&a, 0, TMC2209_REPLY_LEN, 0, TMC2209_IOIN);
    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_RELAY, RPC_RELAY_SEND, &a, n));
    TEST_ASSERT_TRUE(tmc2209_all_owned_valid(&g_dev));

    uint8_t datagram[TMC2209_WRITE_LEN];
    tmc2209_frame_write(datagram, 0, TMC2209_SGTHRS, 0x11U);

    n = relay_args(&a, 0, 0, datagram, sizeof(datagram)); /* a write has no reply */
    TEST_ASSERT_EQUAL(RPC_OK, call(RPC_NS_RELAY, RPC_RELAY_SEND, &a, n));
    TEST_ASSERT_FALSE(tmc2209_all_owned_valid(&g_dev));
}

void test_rpc_relay_refuses_an_oversized_datagram(void)
{
    rpc_setup(false);

    /* Claims more than the part's longest datagram, and sends that much, so
       what is refused is the size and not a length that disagrees with it. */
    relay_args_t a;
    memset(&a, 0, sizeof(a));
    a.s.idx   = 0;
    a.s.count = RPC_RELAY_MAX_BYTES + 1U;

    size_t n = sizeof(rpc_relay_send_args) + RPC_RELAY_MAX_BYTES + 1U;
    TEST_ASSERT_EQUAL(RPC_ARG, call(RPC_NS_RELAY, RPC_RELAY_SEND, &a, n));
}

/* ── Variable-length replies ────────────────────────────────────────────── */

/*
 * A reply ending in a flexible array member is the one shape whose length no
 * table can hold, because sizeof() stops at that member. So the bound is
 * declared by hand, and these two are what keep it honest: one that the real
 * length reaches the wire, one that a handler outgrowing its bound is reported
 * rather than quietly emptied.
 */

#define VAR_NS  RPC_NS_FILM  /* an index this build registers nothing else on */
#define VAR_MAX 16U

static size_t g_var_claim;   /* how much the fake handler says it wrote */

static rpc_status_t var_handler(const void *args, size_t args_len, void *ret, size_t *ret_len)
{
    (void)args;
    (void)args_len;

    memset(ret, 0xA5, g_var_claim);
    *ret_len = g_var_claim;
    return RPC_OK;
}

static const rpc_method_t g_var_methods[1] = {
    [0] = RPC_METHOD_VAR_GET(var_handler, VAR_MAX),
};

static void install_var_method(size_t claim)
{
    rpc_setup(true);
    g_var_claim = claim;
    TEST_ASSERT_TRUE(rpc_register(VAR_NS, g_var_methods, 1));
}

void test_rpc_a_variable_reply_travels_at_its_real_length(void)
{
    install_var_method(VAR_MAX);
    TEST_ASSERT_EQUAL(RPC_OK, call(VAR_NS, 0, NULL, 0));
    TEST_ASSERT_EQUAL_size_t(VAR_MAX, g_ret_len);

    /* Shorter than the bound is the ordinary case, and it must not be padded
       out to it: the length on the wire is what the handler produced. */
    install_var_method(4);
    TEST_ASSERT_EQUAL(RPC_OK, call(VAR_NS, 0, NULL, 0));
    TEST_ASSERT_EQUAL_size_t(4, g_ret_len);
}

/*
 * Reported, because by the time the handler says so it has already written past
 * the room the table promised. RPC_OK with an empty payload would read as a
 * method that had nothing to say, which is how a bound too small to hold one
 * element stays invisible.
 */
void test_rpc_a_handler_that_overruns_its_bound_is_not_a_success(void)
{
    install_var_method(VAR_MAX + 1U);

    TEST_ASSERT_EQUAL(RPC_INTERNAL, call(VAR_NS, 0, NULL, 0));
    TEST_ASSERT_EQUAL_size_t(0, g_ret_len);
}

void run_rpc_tests(void)
{
    RUN_TEST(test_rpc_unknown_namespace_and_method);
    RUN_TEST(test_rpc_unknown_device_is_a_bad_argument);
    RUN_TEST(test_rpc_a_payload_of_the_wrong_length_is_a_bad_frame);
    RUN_TEST(test_rpc_a_failing_call_carries_no_payload);
    RUN_TEST(test_rpc_poll_returns_what_the_device_holds);
    RUN_TEST(test_rpc_read_serves_the_cache_and_refuses_an_empty_slot);
    RUN_TEST(test_rpc_write_batch_lands_on_the_device);
    RUN_TEST(test_rpc_a_batch_that_lies_about_its_count_is_a_bad_frame);
    RUN_TEST(test_rpc_poll_health_reports_the_conditions);
    RUN_TEST(test_rpc_verify_config_reports_agreement_as_a_value);
    RUN_TEST(test_rpc_transport_faults_reach_the_wire_as_themselves);
    RUN_TEST(test_rpc_an_unconfirmed_write_is_not_reported_as_a_write);
    RUN_TEST(test_rpc_a_missing_backend_is_not_a_failure_to_move);
    RUN_TEST(test_rpc_lines_drive_and_read_back);
    RUN_TEST(test_rpc_enable_applies_the_parts_polarity);
    RUN_TEST(test_rpc_an_unwired_line_is_refused_not_guessed);
    RUN_TEST(test_rpc_relay_hands_back_the_reply_undecoded);
    RUN_TEST(test_rpc_relay_reports_silence_without_failing_the_call);
    RUN_TEST(test_rpc_relay_writes_void_the_cache_and_reads_do_not);
    RUN_TEST(test_rpc_relay_refuses_an_oversized_datagram);

    RUN_TEST(test_rpc_a_variable_reply_travels_at_its_real_length);
    RUN_TEST(test_rpc_a_handler_that_overruns_its_bound_is_not_a_success);
}
