/*
 * The wire format is the one thing both ends compile, so what is worth testing
 * is not that a field survives a roundtrip inside one process, but that the
 * bytes are the ones promised: fixed offsets, little-endian, declared padding.
 * A test that only read back what it wrote would pass on a broken layout.
 *
 * The assertions in rpc_proto.h already fail the build if a struct changes
 * size. What they cannot see is which byte went where, so that is what is
 * pinned here.
 */

#include <stdint.h>
#include <string.h>

#include "crc16.h"
#include "rpc_frame.h"

/* The frame layer moves bytes and does not know what a namespace or a status
   means, so neither does this test. Any numbers will do, and using the ones
   this image happens to serve would be the coupling rpc_proto.h was split to
   avoid. */
#define A_NAMESPACE 2U
#define A_METHOD    7U
#define A_STATUS    10U
#include "unity.h"

/* ── Layout ─────────────────────────────────────────────────────────────── */

/* Every header is the same length, which is what keeps a payload's uint32_t
   fields at offsets divisible by four. Little else in the design survives this
   changing. */
void test_frame_headers_are_all_one_length(void)
{
    TEST_ASSERT_EQUAL_size_t(8, sizeof(rpc_req_hdr_t));
    TEST_ASSERT_EQUAL_size_t(8, sizeof(rpc_rep_hdr_t));
    TEST_ASSERT_EQUAL_size_t(8, sizeof(rpc_log_hdr_t));
    TEST_ASSERT_EQUAL_size_t(RPC_HDR_LEN, sizeof(rpc_req_hdr_t));
}

void test_frame_payload_begins_aligned_after_the_header(void)
{
    rpc_buf_t b;

    TEST_ASSERT_EQUAL_PTR(&b.bytes[RPC_HDR_LEN], rpc_payload(&b));

    uintptr_t at = (uintptr_t)rpc_payload(&b);
    TEST_ASSERT_EQUAL_UINT(0, at % 4U); /* enough for any field on this wire */
}

void test_frame_request_header_is_where_it_says(void)
{
    rpc_buf_t b;
    memset(&b, 0xAA, sizeof(b)); /* so declared padding is visibly overwritten */

    size_t len = rpc_frame_seal_req(&b, 0x1234, A_NAMESPACE, A_METHOD, 0);
    TEST_ASSERT_EQUAL_size_t(RPC_HDR_LEN + RPC_CRC_LEN, len);

    const uint8_t want[RPC_HDR_LEN] = {
        RPC_FRAME_REQ, A_NAMESPACE, A_METHOD, 0x00, 0x34, 0x12, /* id, low byte first */
        0x00,          0x00,
    };
    TEST_ASSERT_EQUAL_MEMORY(want, b.bytes, sizeof(want));
}

void test_frame_reply_header_is_where_it_says(void)
{
    rpc_buf_t b;
    memset(&b, 0xAA, sizeof(b));

    size_t len = rpc_frame_seal_rep(&b, 0x0709, A_STATUS, 0);
    TEST_ASSERT_EQUAL_size_t(RPC_HDR_LEN + RPC_CRC_LEN, len);

    const uint8_t want[RPC_HDR_LEN] = {
        RPC_FRAME_REP, A_STATUS, 0x00, 0x00, 0x09, 0x07, 0x00, 0x00,
    };
    TEST_ASSERT_EQUAL_MEMORY(want, b.bytes, sizeof(want));
}

void test_frame_log_header_is_where_it_says(void)
{
    rpc_buf_t b;
    memset(&b, 0xAA, sizeof(b));

    size_t len = rpc_frame_seal_log(&b, 3, 0x11223344U, 0);
    TEST_ASSERT_EQUAL_size_t(RPC_HDR_LEN + RPC_CRC_LEN, len);

    const uint8_t want[RPC_HDR_LEN] = {
        RPC_FRAME_LOG, 0x03, 0x00, 0x00, 0x44, 0x33, 0x22, 0x11,
    };
    TEST_ASSERT_EQUAL_MEMORY(want, b.bytes, sizeof(want));
}

/*
 * Two identical calls have to produce two identical frames. They would not if a
 * header's padding were left holding whatever the previous frame put in the
 * buffer, and the failure would be a CRC that changes for an answer that does
 * not. Sealing writes the header whole, which is what makes this hold.
 */
void test_frame_padding_is_written_not_inherited(void)
{
    rpc_buf_t clean;
    rpc_buf_t dirty;

    memset(&clean, 0x00, sizeof(clean));
    memset(&dirty, 0xFF, sizeof(dirty));

    size_t a = rpc_frame_seal_rep(&clean, 9, A_STATUS, 0);
    size_t b = rpc_frame_seal_rep(&dirty, 9, A_STATUS, 0);

    TEST_ASSERT_EQUAL_size_t(a, b);
    TEST_ASSERT_EQUAL_MEMORY(clean.bytes, dirty.bytes, a);
}

/* ── Roundtrip ──────────────────────────────────────────────────────────── */

void test_frame_carries_a_payload_back_unchanged(void)
{
    rpc_buf_t b;

    const uint8_t payload[] = { 0xDE, 0xAD, 0xBE, 0xEF, 0x01, 0x02 };
    memcpy(rpc_payload(&b), payload, sizeof(payload));

    size_t len = rpc_frame_seal_rep(&b, 7, RPC_OK, sizeof(payload));
    TEST_ASSERT_EQUAL_size_t(RPC_HDR_LEN + sizeof(payload) + RPC_CRC_LEN, len);

    rpc_view_t v;
    TEST_ASSERT_TRUE(rpc_frame_open(&b, len, &v));
    TEST_ASSERT_EQUAL_UINT8(RPC_FRAME_REP, v.type);
    TEST_ASSERT_EQUAL_size_t(sizeof(payload), v.payload_len);
    TEST_ASSERT_EQUAL_MEMORY(payload, v.payload, sizeof(payload));

    const rpc_rep_hdr_t *h = v.hdr;
    TEST_ASSERT_EQUAL_UINT16(7, h->id);
    TEST_ASSERT_EQUAL_UINT8(RPC_OK, h->status);
}

void test_frame_with_no_payload_reports_none(void)
{
    rpc_buf_t b;

    size_t len = rpc_frame_seal_req(&b, 1, A_NAMESPACE, A_METHOD, 0);

    rpc_view_t v;
    TEST_ASSERT_TRUE(rpc_frame_open(&b, len, &v));
    TEST_ASSERT_EQUAL_size_t(0, v.payload_len);

    const rpc_req_hdr_t *h = v.hdr;
    TEST_ASSERT_EQUAL_UINT16(1, h->id);
    TEST_ASSERT_EQUAL_UINT8(A_NAMESPACE, h->ns);
    TEST_ASSERT_EQUAL_UINT8(A_METHOD, h->method);
}

/* ── Refusals ───────────────────────────────────────────────────────────── */

void test_frame_refuses_a_payload_that_does_not_fit(void)
{
    rpc_buf_t b;

    TEST_ASSERT_EQUAL_size_t(0, rpc_frame_seal_rep(&b, 1, RPC_OK, RPC_MAX_PAYLOAD + 1U));
    TEST_ASSERT_GREATER_THAN(0, rpc_frame_seal_rep(&b, 1, RPC_OK, RPC_MAX_PAYLOAD));
}

void test_frame_rejects_corrupt_frames(void)
{
    rpc_buf_t b;

    const uint8_t payload[] = { 0x11, 0x22, 0x33, 0x44 };
    memcpy(rpc_payload(&b), payload, sizeof(payload));
    size_t len = rpc_frame_seal_req(&b, 1, A_NAMESPACE, A_METHOD, sizeof(payload));

    rpc_view_t v;
    TEST_ASSERT_TRUE(rpc_frame_open(&b, len, &v));

    /* Every single-bit flip anywhere in the frame has to be caught, since a
     * frame that decodes is a call that runs. */
    for (size_t i = 0; i < len; i++) {
        for (unsigned bit = 0; bit < 8; bit++) {
            b.bytes[i] ^= (uint8_t)(1U << bit);
            TEST_ASSERT_FALSE(rpc_frame_open(&b, len, &v));
            b.bytes[i] ^= (uint8_t)(1U << bit);
        }
    }

    TEST_ASSERT_TRUE(rpc_frame_open(&b, len, &v)); /* and it still opens after */
}

/* A header and a CRC is the shortest thing that can be a frame, so anything
 * under that is not one however well its bytes happen to check out. */
void test_frame_rejects_a_runt(void)
{
    rpc_buf_t  b;
    rpc_view_t v;

    size_t len = rpc_frame_seal_req(&b, 1, A_NAMESPACE, A_METHOD, 0);

    for (size_t shorter = 0; shorter < len; shorter++) {
        TEST_ASSERT_FALSE(rpc_frame_open(&b, shorter, &v));
    }

    TEST_ASSERT_FALSE(rpc_frame_open(&b, RPC_MAX_FRAME + 1U, &v));
}

/* With a CRC that agrees, so what is refused is the type itself rather than
 * the damage done in changing it. */
void test_frame_rejects_unknown_frame_type(void)
{
    rpc_buf_t b;

    size_t len  = rpc_frame_seal_req(&b, 1, A_NAMESPACE, A_METHOD, 0);
    size_t body = len - RPC_CRC_LEN;

    b.bytes[0] = 0x7F;

    uint16_t crc      = crc16_ccitt(b.bytes, body);
    b.bytes[body]     = (uint8_t)(crc & 0xFFU);
    b.bytes[body + 1] = (uint8_t)((crc >> 8) & 0xFFU);

    rpc_view_t v;
    TEST_ASSERT_FALSE(rpc_frame_open(&b, len, &v));
}

void run_rpc_frame_tests(void)
{
    RUN_TEST(test_frame_headers_are_all_one_length);
    RUN_TEST(test_frame_payload_begins_aligned_after_the_header);
    RUN_TEST(test_frame_request_header_is_where_it_says);
    RUN_TEST(test_frame_reply_header_is_where_it_says);
    RUN_TEST(test_frame_log_header_is_where_it_says);
    RUN_TEST(test_frame_padding_is_written_not_inherited);
    RUN_TEST(test_frame_carries_a_payload_back_unchanged);
    RUN_TEST(test_frame_with_no_payload_reports_none);
    RUN_TEST(test_frame_refuses_a_payload_that_does_not_fit);
    RUN_TEST(test_frame_rejects_corrupt_frames);
    RUN_TEST(test_frame_rejects_a_runt);
    RUN_TEST(test_frame_rejects_unknown_frame_type);
}
