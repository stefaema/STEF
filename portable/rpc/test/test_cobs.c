/*
 * COBS is worth testing at its edges rather than in the middle: the cases that
 * break it are a zero at each end, a run of exactly 254 non-zero bytes, and a
 * receiver that has to find its place again after damage.
 */

#include <string.h>

#include "cobs.h"
#include "unity.h"

static void roundtrip(const uint8_t *data, size_t len)
{
    uint8_t enc[COBS_ENCODED_MAX(600)];
    uint8_t dec[600];

    size_t n = cobs_encode(data, len, enc, sizeof(enc));
    TEST_ASSERT_GREATER_THAN(0, n);

    for (size_t i = 0; i < n; i++) {
        TEST_ASSERT_NOT_EQUAL_MESSAGE(0, enc[i], "encoding contains a delimiter");
    }

    size_t back = cobs_decode(enc, n, dec, sizeof(dec));
    TEST_ASSERT_EQUAL_size_t(len, back);
    if (len > 0) {
        TEST_ASSERT_EQUAL_MEMORY(data, dec, len);
    }
}

void test_cobs_roundtrips_empty(void)
{
    roundtrip((const uint8_t *)"", 0);
}

void test_cobs_roundtrips_zeros(void)
{
    const uint8_t only_zeros[] = { 0, 0, 0 };
    roundtrip(only_zeros, sizeof(only_zeros));

    const uint8_t edges[] = { 0, 1, 2, 0 };
    roundtrip(edges, sizeof(edges));
}

/* 254 is where a group fills up and the encoder has to start another. */
void test_cobs_roundtrips_group_boundaries(void)
{
    uint8_t run[600];
    memset(run, 0xAB, sizeof(run));

    for (size_t len = 252; len <= 258; len++) {
        roundtrip(run, len);
    }

    roundtrip(run, sizeof(run));
}

void test_cobs_roundtrips_mixed(void)
{
    uint8_t data[500];
    for (size_t i = 0; i < sizeof(data); i++) {
        data[i] = (uint8_t)(i % 7); /* zeros every seventh byte */
    }
    roundtrip(data, sizeof(data));
}

void test_cobs_encode_refuses_short_output(void)
{
    const uint8_t data[] = { 1, 2, 3 };
    uint8_t       enc[2];

    TEST_ASSERT_EQUAL_size_t(0, cobs_encode(data, sizeof(data), enc, sizeof(enc)));
}

void test_cobs_decode_rejects_malformed(void)
{
    uint8_t out[16];

    /* A delimiter inside the run: whatever this is, it is not one frame. */
    const uint8_t embedded_zero[] = { 0x02, 0x41, 0x00, 0x01 };
    TEST_ASSERT_EQUAL_size_t(0,
                             cobs_decode(embedded_zero, sizeof(embedded_zero), out, sizeof(out)));

    /* A group that claims more bytes than the run holds. */
    const uint8_t overruns[] = { 0x05, 0x41 };
    TEST_ASSERT_EQUAL_size_t(0, cobs_decode(overruns, sizeof(overruns), out, sizeof(out)));

    /* A frame that decodes to more than the caller has room for. */
    const uint8_t too_big[] = { 0x04, 1, 2, 3 };
    uint8_t       tiny[2];
    TEST_ASSERT_EQUAL_size_t(0, cobs_decode(too_big, sizeof(too_big), tiny, sizeof(tiny)));
}

/*
 * The property the framing was chosen for. Corrupt a frame arbitrarily and the
 * next delimiter still starts a good one, so a receiver loses at most the frame
 * it was in the middle of.
 */
void test_cobs_resyncs_after_damage(void)
{
    const uint8_t good[] = { 0xDE, 0xAD, 0x00, 0xBE, 0xEF };

    uint8_t stream[64];
    size_t  at = 0;

    /* Garbage, then a delimiter, then a real frame. */
    for (uint8_t i = 1; i <= 9; i++) {
        stream[at++] = (uint8_t)(i * 3);
    }
    stream[at++] = 0x00;

    size_t enc = cobs_encode(good, sizeof(good), stream + at, sizeof(stream) - at);
    TEST_ASSERT_GREATER_THAN(0, enc);
    at += enc;

    /* Read as a receiver would: split on zeros, decode each run. */
    size_t  start = 0;
    uint8_t out[64];
    size_t  recovered = 0;

    for (size_t i = 0; i <= at; i++) {
        if (i < at && stream[i] != 0x00) {
            continue;
        }
        size_t len = cobs_decode(stream + start, i - start, out, sizeof(out));
        if (len == sizeof(good) && memcmp(out, good, len) == 0) {
            recovered++;
        }
        start = i + 1;
    }

    TEST_ASSERT_EQUAL_size_t(1, recovered);
}

void run_cobs_tests(void)
{
    RUN_TEST(test_cobs_roundtrips_empty);
    RUN_TEST(test_cobs_roundtrips_zeros);
    RUN_TEST(test_cobs_roundtrips_group_boundaries);
    RUN_TEST(test_cobs_roundtrips_mixed);
    RUN_TEST(test_cobs_encode_refuses_short_output);
    RUN_TEST(test_cobs_decode_rejects_malformed);
    RUN_TEST(test_cobs_resyncs_after_damage);
}
