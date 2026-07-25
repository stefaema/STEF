/*
 * test_frame.c — the pure layer: CRC, datagram construction, reply parsing.
 *
 * The CRC vectors are not self-generated. They come from the Python
 * implementation in cinescaner-drive, which was exercised against real
 * silicon, so agreeing with them means agreeing with hardware rather than
 * merely agreeing with ourselves.
 */

#include "unity.h"
#include "tmc2209_frame.h"
#include "tmc2209_reg.h"

#include <string.h>

static void test_crc8_reference_vectors(void)
{
    const uint8_t read_gconf_a0[]   = { 0x05, 0x00, 0x00 };
    const uint8_t read_chopconf[]   = { 0x05, 0x00, 0x6C };
    const uint8_t read_gconf_a2[]   = { 0x05, 0x02, 0x00 };
    const uint8_t write_gconf[]     = { 0x05, 0x00, 0x80, 0x00, 0x00, 0x01, 0x01 };
    const uint8_t write_chopconf[]  = { 0x05, 0x00, 0xEC, 0x10, 0x00, 0x00, 0x53 };
    const uint8_t reply_gconf[]     = { 0x05, 0xFF, 0x00, 0x00, 0x00, 0x01, 0x01 };
    const uint8_t just_ff[]         = { 0xFF };

    TEST_ASSERT_EQUAL_HEX8(0x48, tmc2209_crc8(read_gconf_a0, sizeof read_gconf_a0));
    TEST_ASSERT_EQUAL_HEX8(0xCA, tmc2209_crc8(read_chopconf, sizeof read_chopconf));
    TEST_ASSERT_EQUAL_HEX8(0x13, tmc2209_crc8(read_gconf_a2, sizeof read_gconf_a2));
    TEST_ASSERT_EQUAL_HEX8(0x76, tmc2209_crc8(write_gconf, sizeof write_gconf));
    TEST_ASSERT_EQUAL_HEX8(0x9C, tmc2209_crc8(write_chopconf, sizeof write_chopconf));
    TEST_ASSERT_EQUAL_HEX8(0xBB, tmc2209_crc8(reply_gconf, sizeof reply_gconf));
    TEST_ASSERT_EQUAL_HEX8(0xF3, tmc2209_crc8(just_ff, sizeof just_ff));
    TEST_ASSERT_EQUAL_HEX8(0x00, tmc2209_crc8(NULL, 0));
}

/* The address changing the CRC is what makes a shared bus safe: a datagram
   for driver 0 cannot be mistaken for one for driver 2. */
static void test_crc8_distinguishes_slave_address(void)
{
    uint8_t a0[TMC2209_READ_REQ_LEN], a2[TMC2209_READ_REQ_LEN];
    tmc2209_frame_read_request(a0, 0, TMC2209_GCONF);
    tmc2209_frame_read_request(a2, 2, TMC2209_GCONF);
    TEST_ASSERT_NOT_EQUAL(a0[3], a2[3]);
}

static void test_write_datagram_layout(void)
{
    uint8_t dg[TMC2209_WRITE_LEN];
    tmc2209_frame_write(dg, 0, TMC2209_CHOPCONF, 0x10000053u);

    TEST_ASSERT_EQUAL_HEX8(TMC2209_SYNC, dg[0]);
    TEST_ASSERT_EQUAL_HEX8(0x00, dg[1]);
    TEST_ASSERT_EQUAL_HEX8(0xEC, dg[2]);   /* 0x6C with bit 7 set marks a write */
    TEST_ASSERT_EQUAL_HEX8(0x10, dg[3]);   /* MSB first */
    TEST_ASSERT_EQUAL_HEX8(0x00, dg[4]);
    TEST_ASSERT_EQUAL_HEX8(0x00, dg[5]);
    TEST_ASSERT_EQUAL_HEX8(0x53, dg[6]);
    TEST_ASSERT_EQUAL_HEX8(0x9C, dg[7]);
}

static void test_read_request_layout(void)
{
    uint8_t req[TMC2209_READ_REQ_LEN];
    tmc2209_frame_read_request(req, 0, TMC2209_CHOPCONF);

    TEST_ASSERT_EQUAL_HEX8(TMC2209_SYNC, req[0]);
    TEST_ASSERT_EQUAL_HEX8(0x00, req[1]);
    TEST_ASSERT_EQUAL_HEX8(0x6C, req[2]);   /* bit 7 clear marks a read */
    TEST_ASSERT_EQUAL_HEX8(0xCA, req[3]);
}

static void test_slave_address_is_masked_to_two_bits(void)
{
    uint8_t dg[TMC2209_WRITE_LEN];
    tmc2209_frame_write(dg, 0xFF, TMC2209_GCONF, 0);
    TEST_ASSERT_EQUAL_HEX8(0x03, dg[1]);
}

static void make_reply(uint8_t out[TMC2209_REPLY_LEN], uint8_t reg, uint32_t v)
{
    out[0] = TMC2209_SYNC;
    out[1] = TMC2209_MASTER_ADDR;
    out[2] = reg;
    out[3] = (uint8_t)(v >> 24);
    out[4] = (uint8_t)(v >> 16);
    out[5] = (uint8_t)(v >> 8);
    out[6] = (uint8_t)v;
    out[7] = tmc2209_crc8(out, 7);
}

static void test_parse_reply_accepts_valid_frame(void)
{
    uint8_t reply[TMC2209_REPLY_LEN];
    make_reply(reply, TMC2209_GCONF, 0x00000101u);

    uint32_t value = 0;
    TEST_ASSERT_EQUAL(TMC2209_OK, tmc2209_frame_parse_reply(reply, TMC2209_GCONF, &value));
    TEST_ASSERT_EQUAL_HEX32(0x00000101u, value);
}

static void test_parse_reply_rejects_bad_sync(void)
{
    uint8_t reply[TMC2209_REPLY_LEN];
    make_reply(reply, TMC2209_GCONF, 0);
    reply[0] = 0x06;
    reply[7] = tmc2209_crc8(reply, 7);   /* keep CRC valid so sync is what fails */

    uint32_t value = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_SYNC, tmc2209_frame_parse_reply(reply, TMC2209_GCONF, &value));
}

static void test_parse_reply_rejects_non_master_address(void)
{
    uint8_t reply[TMC2209_REPLY_LEN];
    make_reply(reply, TMC2209_GCONF, 0);
    reply[1] = 0x00;
    reply[7] = tmc2209_crc8(reply, 7);

    uint32_t value = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_SYNC, tmc2209_frame_parse_reply(reply, TMC2209_GCONF, &value));
}

/* A reply for a register we did not ask about means a second driver answered.
   That is a distinct failure from corruption, because retrying cannot fix it. */
static void test_parse_reply_rejects_wrong_register(void)
{
    uint8_t reply[TMC2209_REPLY_LEN];
    make_reply(reply, TMC2209_CHOPCONF, 0);

    uint32_t value = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_REG, tmc2209_frame_parse_reply(reply, TMC2209_GCONF, &value));
}

static void test_parse_reply_rejects_bad_crc(void)
{
    uint8_t reply[TMC2209_REPLY_LEN];
    make_reply(reply, TMC2209_GCONF, 0x12345678u);
    reply[7] ^= 0xFFu;

    uint32_t value = 0;
    TEST_ASSERT_EQUAL(TMC2209_ERR_CRC, tmc2209_frame_parse_reply(reply, TMC2209_GCONF, &value));
}

static void test_parse_reply_leaves_output_untouched_on_failure(void)
{
    uint8_t reply[TMC2209_REPLY_LEN];
    make_reply(reply, TMC2209_GCONF, 0x12345678u);
    reply[7] ^= 0xFFu;

    uint32_t value = 0xDEADBEEFu;
    (void)tmc2209_frame_parse_reply(reply, TMC2209_GCONF, &value);
    TEST_ASSERT_EQUAL_HEX32(0xDEADBEEFu, value);
}

static void test_parse_reply_detects_every_single_bit_corruption(void)
{
    uint8_t clean[TMC2209_REPLY_LEN];
    make_reply(clean, TMC2209_DRV_STATUS, 0xA5A5A5A5u);

    for (size_t byte = 0; byte < TMC2209_REPLY_LEN; byte++) {
        for (int bit = 0; bit < 8; bit++) {
            uint8_t corrupt[TMC2209_REPLY_LEN];
            memcpy(corrupt, clean, sizeof clean);
            corrupt[byte] ^= (uint8_t)(1u << bit);

            uint32_t value = 0;
            TEST_ASSERT_NOT_EQUAL(
                TMC2209_OK,
                tmc2209_frame_parse_reply(corrupt, TMC2209_DRV_STATUS, &value));
        }
    }
}

void run_frame_tests(void)
{
    RUN_TEST(test_crc8_reference_vectors);
    RUN_TEST(test_crc8_distinguishes_slave_address);
    RUN_TEST(test_write_datagram_layout);
    RUN_TEST(test_read_request_layout);
    RUN_TEST(test_slave_address_is_masked_to_two_bits);
    RUN_TEST(test_parse_reply_accepts_valid_frame);
    RUN_TEST(test_parse_reply_rejects_bad_sync);
    RUN_TEST(test_parse_reply_rejects_non_master_address);
    RUN_TEST(test_parse_reply_rejects_wrong_register);
    RUN_TEST(test_parse_reply_rejects_bad_crc);
    RUN_TEST(test_parse_reply_leaves_output_untouched_on_failure);
    RUN_TEST(test_parse_reply_detects_every_single_bit_corruption);
}
