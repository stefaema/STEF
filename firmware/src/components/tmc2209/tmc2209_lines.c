#include "tmc2209.h"

/* DIAG is the only line the driver drives. The other three it reads, which is
   what makes them writable from here. */
bool tmc2209_line_is_output(tmc2209_line_t line)
{
    return line == TMC2209_LINE_ENN
        || line == TMC2209_LINE_DIR
        || line == TMC2209_LINE_STEP;
}

bool tmc2209_line_is_wired(const tmc2209_t *dev, tmc2209_line_t line)
{
    if (!dev || !dev->lines || line >= TMC2209_LINE_COUNT) {
        return false;
    }
    return (dev->lines->wired & TMC2209_LINE_BIT(line)) != 0;
}

static tmc2209_err_t check_line(const tmc2209_t *dev, tmc2209_line_t line)
{
    if (!dev || line >= TMC2209_LINE_COUNT) {
        return TMC2209_ERR_ARG; /* The line or the device doesn't exist */
    }
    if (!dev->lines) {
        return TMC2209_ERR_NO_BACKEND;
    }
    if (!tmc2209_line_is_wired(dev, line)) {
        return TMC2209_ERR_UNWIRED;
    }
    return TMC2209_OK;
}

tmc2209_err_t tmc2209_attach_lines(tmc2209_t *dev, const tmc2209_lines_t *lines)
{
    if (!dev) {
        return TMC2209_ERR_ARG;
    }
    if (lines && (!lines->read || !lines->write)) {
        return TMC2209_ERR_ARG;
    }
    dev->lines = lines;
    return TMC2209_OK;
}

tmc2209_err_t tmc2209_line_read(const tmc2209_t *dev, tmc2209_line_t line, bool *level)
{
    if (!level) {
        return TMC2209_ERR_ARG;
    }
    tmc2209_err_t err = check_line(dev, line);
    if (err != TMC2209_OK) {
        return err;
    }

    int got = dev->lines->read(dev->lines->ctx, line);
    if (got < 0) {
        return TMC2209_ERR_IO;
    }
    *level = (got != 0);
    return TMC2209_OK;
}

tmc2209_err_t tmc2209_line_write(tmc2209_t *dev, tmc2209_line_t line, bool level)
{
    tmc2209_err_t err = check_line(dev, line);
    if (err != TMC2209_OK) {
        return err;
    }
    /* Checked after wiring, so a board that does not connect DIAG reports that
       rather than a policy violation it was never in a position to commit. */
    if (!tmc2209_line_is_output(line)) {
        return TMC2209_ERR_ACCESS;
    }
    /* A stepgen owns the pin it pulses. Letting a level write through as well
       would give one pin two owners, and which of them the pad ends up
       following is a detail of whichever peripheral the board happens to use.
       Reads stay open: observing a level disturbs nothing. */
    if (line == TMC2209_LINE_STEP && dev->stepgen) {
        return TMC2209_ERR_ACCESS;
    }

    return (dev->lines->write(dev->lines->ctx, line, level) < 0)
        ? TMC2209_ERR_IO
        : TMC2209_OK;
}

/* ── Meaning ────────────────────────────────────────────────────────────── */

tmc2209_err_t tmc2209_enable(tmc2209_t *dev, bool on)
{
    return tmc2209_line_write(dev, TMC2209_LINE_ENN, !on);
}

tmc2209_err_t tmc2209_is_enabled(const tmc2209_t *dev, bool *on)
{
    bool level = false;
    tmc2209_err_t err = tmc2209_line_read(dev, TMC2209_LINE_ENN, &level);
    if (err == TMC2209_OK) {
        *on = !level;
    }
    return err;
}
