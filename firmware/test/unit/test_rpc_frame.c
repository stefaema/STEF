/*
 * The wire format is the one thing both ends compile, so what is worth testing
 * is not that a field survives a roundtrip inside one process, but that the
 * bytes are the ones promised: fixed widths, little-endian, no padding. A test
 * that only reads back what it wrote would pass on a broken layout.
 */

#include <string.h>

#include "rpc_wire.h"

/* The wire moves bytes and does not know what a namespace or a status means,
   so neither does this test. Any numbers will do, and using the ones this
   image happens to serve would be the coupling rpc_proto.h was split to
   avoid. */
#define A_NAMESPACE  2u
#define A_METHOD     7u
#define A_STATUS     10u
#include "unity.h"

void test_wire_writes_little_endian_fixed_widths(void)
{
    uint8_t      buf[32];
    rpc_writer_t w;

    rpc_w_init(&w, buf, sizeof(buf));
    rpc_w_u8(&w, 0x11);
    rpc_w_u16(&w, 0x2233);
    rpc_w_u32(&w, 0x44556677u);
    rpc_w_i32(&w, -2);
    rpc_w_bool(&w, true);

    TEST_ASSERT_TRUE(w.ok);
    TEST_ASSERT_EQUAL_size_t(1 + 2 + 4 + 4 + 1, w.len);

    const uint8_t want[] = { 0x11,
                             0x33, 0x22,
                             0x77, 0x66, 0x55, 0x44,
                             0xFE, 0xFF, 0xFF, 0xFF,
                             0x01 };
    TEST_ASSERT_EQUAL_MEMORY(want, buf, sizeof(want));
}

void test_wire_reads_back_what_it_wrote(void)
{
    uint8_t      buf[64];
    rpc_writer_t w;

    rpc_w_init(&w, buf, sizeof(buf));
    rpc_w_u32(&w, 0xDEADBEEFu);
    rpc_w_i32(&w, -123456);
    rpc_w_str(&w, "gconf");
    TEST_ASSERT_TRUE(w.ok);

    rpc_reader_t r;
    rpc_r_init(&r, buf, w.len);

    TEST_ASSERT_EQUAL_UINT32(0xDEADBEEFu, rpc_r_u32(&r));
    TEST_ASSERT_EQUAL_INT32(-123456, rpc_r_i32(&r));

    size_t         len = 0;
    const uint8_t *s   = rpc_r_bytes(&r, &len);
    TEST_ASSERT_NOT_NULL(s);
    TEST_ASSERT_EQUAL_size_t(5, len);
    TEST_ASSERT_EQUAL_MEMORY("gconf", s, 5);

    TEST_ASSERT_TRUE(rpc_r_done(&r));
}

/* The writer collects failures instead of reporting each one, so what must be
 * true is that an overflow anywhere makes the whole frame unusable. */
void test_wire_overflow_poisons_the_writer(void)
{
    uint8_t      buf[4];
    rpc_writer_t w;

    rpc_w_init(&w, buf, sizeof(buf));
    rpc_w_u32(&w, 1);
    TEST_ASSERT_TRUE(w.ok);

    rpc_w_u8(&w, 2);
    TEST_ASSERT_FALSE(w.ok);

    rpc_w_u8(&w, 3); /* a no-op, not a wild write */
    TEST_ASSERT_FALSE(w.ok);
    TEST_ASSERT_EQUAL_size_t(4, w.len);
    TEST_ASSERT_EQUAL_size_t(0, rpc_frame_finish(&w));
}

void test_wire_underrun_poisons_the_reader(void)
{
    const uint8_t buf[] = { 0x01, 0x02 };
    rpc_reader_t  r;

    rpc_r_init(&r, buf, sizeof(buf));
    TEST_ASSERT_EQUAL_UINT16(0x0201, rpc_r_u16(&r));
    TEST_ASSERT_TRUE(rpc_r_done(&r));

    TEST_ASSERT_EQUAL_UINT8(0, rpc_r_u8(&r));
    TEST_ASSERT_FALSE(r.ok);
    TEST_ASSERT_FALSE(rpc_r_done(&r));
}

/* Trailing bytes mean the two ends disagree about what a method takes. */
void test_wire_leftover_bytes_are_not_done(void)
{
    const uint8_t buf[] = { 0x01, 0x02, 0x03 };
    rpc_reader_t  r;

    rpc_r_init(&r, buf, sizeof(buf));
    (void)rpc_r_u16(&r);

    TEST_ASSERT_TRUE(r.ok);
    TEST_ASSERT_FALSE(rpc_r_done(&r));
}

void test_wire_request_frame_roundtrips(void)
{
    uint8_t      buf[64];
    rpc_writer_t w;

    rpc_frame_begin_req(&w, buf, sizeof(buf), 0x1234, A_NAMESPACE, A_METHOD);
    size_t len = rpc_frame_finish(&w);
    TEST_ASSERT_GREATER_THAN(0, len);

    uint8_t      type = 0xFF;
    rpc_reader_t r;
    TEST_ASSERT_TRUE(rpc_frame_open(buf, len, &type, &r));
    TEST_ASSERT_EQUAL_UINT8(RPC_FRAME_REQ, type);

    rpc_req_t req;
    TEST_ASSERT_TRUE(rpc_req_header(&r, &req));
    TEST_ASSERT_EQUAL_UINT16(0x1234, req.id);
    TEST_ASSERT_EQUAL_UINT8(A_NAMESPACE, req.ns);
    TEST_ASSERT_EQUAL_UINT8(A_METHOD, req.method);
    TEST_ASSERT_TRUE(rpc_r_done(&r)); /* no arguments, and none left over */
}

void test_wire_reply_frame_carries_status_and_values(void)
{
    uint8_t      buf[64];
    rpc_writer_t w;

    rpc_frame_begin_rep(&w, buf, sizeof(buf), 7, RPC_OK);
    rpc_w_u32(&w, 0x000000C3u);
    size_t len = rpc_frame_finish(&w);

    uint8_t      type = 0xFF;
    rpc_reader_t r;
    TEST_ASSERT_TRUE(rpc_frame_open(buf, len, &type, &r));
    TEST_ASSERT_EQUAL_UINT8(RPC_FRAME_REP, type);
    TEST_ASSERT_EQUAL_UINT16(7, rpc_r_u16(&r));
    TEST_ASSERT_EQUAL_UINT8(RPC_OK, rpc_r_u8(&r));
    TEST_ASSERT_EQUAL_UINT32(0xC3u, rpc_r_u32(&r));
    TEST_ASSERT_TRUE(rpc_r_done(&r));
}

/* A failed handler takes its half-written return values back, and the status
 * is patched in place rather than the frame being built twice. */
void test_wire_rewind_and_restate_status(void)
{
    uint8_t      buf[64];
    rpc_writer_t w;

    rpc_frame_begin_rep(&w, buf, sizeof(buf), 9, RPC_OK);
    size_t mark = w.len;

    rpc_w_u32(&w, 0xAAAAAAAAu);
    rpc_w_rewind(&w, mark);
    rpc_frame_set_status(&w, A_STATUS);

    size_t       len = rpc_frame_finish(&w);
    uint8_t      type = 0xFF;
    rpc_reader_t r;

    TEST_ASSERT_TRUE(rpc_frame_open(buf, len, &type, &r));
    TEST_ASSERT_EQUAL_UINT16(9, rpc_r_u16(&r));
    TEST_ASSERT_EQUAL_UINT8(A_STATUS, rpc_r_u8(&r));
    TEST_ASSERT_TRUE(rpc_r_done(&r)); /* nothing survived the rewind */
}

void test_wire_rejects_corrupt_frames(void)
{
    uint8_t      buf[64];
    rpc_writer_t w;

    rpc_frame_begin_req(&w, buf, sizeof(buf), 1, A_NAMESPACE, A_METHOD);
    rpc_w_u32(&w, 0x11223344u);
    size_t len = rpc_frame_finish(&w);

    uint8_t      type;
    rpc_reader_t r;
    TEST_ASSERT_TRUE(rpc_frame_open(buf, len, &type, &r));

    /* Every single-bit flip in the body has to be caught, since a frame that
     * decodes is a call that runs. */
    for (size_t i = 0; i < len; i++) {
        for (unsigned bit = 0; bit < 8; bit++) {
            buf[i] ^= (uint8_t)(1u << bit);
            TEST_ASSERT_FALSE(rpc_frame_open(buf, len, &type, &r));
            buf[i] ^= (uint8_t)(1u << bit);
        }
    }

    /* Too short to hold a type byte and a CRC. */
    TEST_ASSERT_FALSE(rpc_frame_open(buf, 2, &type, &r));
}

void test_wire_rejects_unknown_frame_type(void)
{
    uint8_t      buf[16];
    rpc_writer_t w;

    rpc_w_init(&w, buf, sizeof(buf));
    rpc_w_u8(&w, 0x7F); /* not one of REQ, REP, LOG */
    rpc_w_u8(&w, 0x00);
    size_t len = rpc_frame_finish(&w);

    uint8_t      type;
    rpc_reader_t r;
    TEST_ASSERT_FALSE(rpc_frame_open(buf, len, &type, &r));
}

void run_wire_tests(void)
{
    RUN_TEST(test_wire_writes_little_endian_fixed_widths);
    RUN_TEST(test_wire_reads_back_what_it_wrote);
    RUN_TEST(test_wire_overflow_poisons_the_writer);
    RUN_TEST(test_wire_underrun_poisons_the_reader);
    RUN_TEST(test_wire_leftover_bytes_are_not_done);
    RUN_TEST(test_wire_request_frame_roundtrips);
    RUN_TEST(test_wire_reply_frame_carries_status_and_values);
    RUN_TEST(test_wire_rewind_and_restate_status);
    RUN_TEST(test_wire_rejects_corrupt_frames);
    RUN_TEST(test_wire_rejects_unknown_frame_type);
}
