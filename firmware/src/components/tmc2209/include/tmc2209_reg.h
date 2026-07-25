/*
 * tmc2209_reg.h — the register table.
 *
 * Two different questions get answered here and must be kept apart: what the
 * *chip* can do, and what our *firmware* configures.
 *
 *   - Access flags (R/W) are the chip's. Eight registers are write-only in
 *     silicon, so asking the device what they hold is a question it cannot
 *     answer. Enforcing that turns a class of bug we shipped in the Python
 *     library into an error return.
 *   - TMC2209_ACC_CONFIG is ours. It marks the ten registers we push and
 *     reflush. Everything else is readable but never commanded.
 *
 * Consequence worth stating: a register being outside our configuration set
 * does not make it unreachable. The diagnostic registers at the end of the
 * table carry no field codecs and are never written, but raw RPC can read
 * them, which is the whole point of separating capability from policy.
 *
 * Two of the chip's registers are absent entirely. OTP_PROG burns one-time
 * fuses, so hand-assembling a passthrough datagram is the right amount of
 * friction. FACTORY_CONF and PWMCONF are present but marked read-only: the
 * silicon allows writes, our policy does not.
 */

#ifndef TMC2209_REG_H
#define TMC2209_REG_H

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    TMC2209_GCONF        = 0x00,
    TMC2209_GSTAT        = 0x01,
    TMC2209_IFCNT        = 0x02,
    TMC2209_SLAVECONF    = 0x03,
    TMC2209_IOIN         = 0x06,
    TMC2209_FACTORY_CONF = 0x07,
    TMC2209_IHOLD_IRUN   = 0x10,
    TMC2209_TPOWERDOWN   = 0x11,
    TMC2209_TSTEP        = 0x12,
    TMC2209_TPWMTHRS     = 0x13,
    TMC2209_TCOOLTHRS    = 0x14,
    TMC2209_VACTUAL      = 0x22,
    TMC2209_SGTHRS       = 0x40,
    TMC2209_SG_RESULT    = 0x41,
    TMC2209_COOLCONF     = 0x42,
    TMC2209_MSCNT        = 0x6A,
    TMC2209_CHOPCONF     = 0x6C,
    TMC2209_DRV_STATUS   = 0x6F,

    /* Readable, never configured. Present so the PC-side diagnostic can see
       the whole device without hand-assembling passthrough datagrams. */
    TMC2209_OTP_READ     = 0x05,
    TMC2209_MSCURACT     = 0x6B,
    TMC2209_PWMCONF      = 0x70,
    TMC2209_PWM_SCALE    = 0x71,
    TMC2209_PWM_AUTO     = 0x72,
} tmc2209_reg_t;

#define TMC2209_REG_COUNT 23

enum {
    TMC2209_ACC_R      = 1u << 0,
    TMC2209_ACC_W      = 1u << 1,
    /* Participates in reflush: a config register whose value we impose after
       a reset or after passthrough left the shadow untrustworthy. GSTAT is
       writable but excluded, since writing it clears latched flags rather
       than restoring configuration. */
    TMC2209_ACC_CONFIG = 1u << 2,
};

/* Slot in the shadow array, or -1 if the register is not one we keep.
   Cutting to 18 is what lets the dirty bitmap be a single uint32_t. */
int         tmc2209_reg_slot(tmc2209_reg_t reg);
uint8_t     tmc2209_reg_access(tmc2209_reg_t reg);   /* 0 if unknown */
uint32_t    tmc2209_reg_reset_value(tmc2209_reg_t reg);
const char *tmc2209_reg_name(tmc2209_reg_t reg);     /* "?" if unknown */

/* Slot-indexed accessors, for iterating the shadow without a reverse lookup.
   Callers must keep slot in [0, TMC2209_REG_COUNT). */
tmc2209_reg_t tmc2209_reg_at(int slot);
uint8_t       tmc2209_reg_access_at(int slot);
uint32_t      tmc2209_reg_reset_at(int slot);

/* ── Field enums ────────────────────────────────────────────────────────── */

typedef enum {
    TMC2209_MRES_256 = 0, TMC2209_MRES_128, TMC2209_MRES_64, TMC2209_MRES_32,
    TMC2209_MRES_16,      TMC2209_MRES_8,   TMC2209_MRES_4,  TMC2209_MRES_2,
    TMC2209_MRES_FULL,
} tmc2209_mres_t;

/* Microsteps per full step, for the rate arithmetic the actuator layer needs. */
uint16_t tmc2209_mres_microsteps(tmc2209_mres_t mres);

typedef enum { TMC2209_TBL_16 = 0, TMC2209_TBL_24, TMC2209_TBL_32, TMC2209_TBL_40 } tmc2209_tbl_t;
typedef enum { TMC2209_SEUP_1 = 0, TMC2209_SEUP_2, TMC2209_SEUP_4, TMC2209_SEUP_8 } tmc2209_seup_t;
typedef enum { TMC2209_SEDN_32 = 0, TMC2209_SEDN_8, TMC2209_SEDN_2, TMC2209_SEDN_1 } tmc2209_sedn_t;

/* ── Field codecs ───────────────────────────────────────────────────────── */

typedef struct {
    bool i_scale_analog;    /* external VREF */
    bool internal_rsense;
    bool en_spreadcycle;    /* 0 = StealthChop */
    bool shaft;             /* invert direction */
    bool index_otpw;
    bool index_step;
    bool pdn_disable;       /* 1 = PDN_UART is the UART pin. Required. */
    bool mstep_reg_select;  /* 1 = mres comes from CHOPCONF, not MS1/MS2. Required. */
    bool multistep_filt;
    bool test_mode;         /* factory use. Never set. */
} tmc2209_gconf_t;

uint32_t        tmc2209_gconf_encode(const tmc2209_gconf_t *g);
tmc2209_gconf_t tmc2209_gconf_decode(uint32_t raw);

typedef struct {
    uint8_t        toff;    /* 0 = driver disabled */
    uint8_t        hstrt;
    uint8_t        hend;
    tmc2209_tbl_t  tbl;
    bool           vsense;
    tmc2209_mres_t mres;
    bool           intpol;
    bool           dedge;
    bool           diss2g;
    bool           diss2vs;
} tmc2209_chopconf_t;

uint32_t           tmc2209_chopconf_encode(const tmc2209_chopconf_t *c);
tmc2209_chopconf_t tmc2209_chopconf_decode(uint32_t raw);

typedef struct {
    uint8_t ihold;       /* 0..31, the tension hold */
    uint8_t irun;        /* 0..31 */
    uint8_t iholddelay;  /* 0..15 */
} tmc2209_ihold_irun_t;

uint32_t             tmc2209_ihold_irun_encode(const tmc2209_ihold_irun_t *i);
tmc2209_ihold_irun_t tmc2209_ihold_irun_decode(uint32_t raw);

typedef struct {
    uint8_t        semin;   /* 0 = CoolStep off */
    tmc2209_seup_t seup;
    uint8_t        semax;
    tmc2209_sedn_t sedn;
    bool           seimin;
} tmc2209_coolconf_t;

uint32_t           tmc2209_coolconf_encode(const tmc2209_coolconf_t *c);
tmc2209_coolconf_t tmc2209_coolconf_decode(uint32_t raw);

typedef struct {
    bool    otpw, ot;             /* overtemperature warning / shutdown */
    bool    s2ga, s2gb;           /* short to ground */
    bool    s2vsa, s2vsb;         /* short to supply */
    bool    ola, olb;             /* open load */
    bool    t120, t143, t150, t157;
    uint8_t cs_actual;            /* 0..31, the current the chip settled on */
    bool    stealth;
    bool    stst;                 /* standstill */
} tmc2209_drv_status_t;

tmc2209_drv_status_t tmc2209_drv_status_decode(uint32_t raw);
/* True for anything that means the output stage has a real problem. */
bool                 tmc2209_drv_status_faulted(const tmc2209_drv_status_t *s);

typedef struct {
    bool reset;    /* driver was reset and lost its configuration */
    bool drv_err;
    bool uv_cp;    /* charge pump undervoltage */
} tmc2209_gstat_t;

uint32_t        tmc2209_gstat_encode(const tmc2209_gstat_t *g);  /* write 1 to clear */
tmc2209_gstat_t tmc2209_gstat_decode(uint32_t raw);

typedef struct {
    bool    enn, ms1, ms2, diag, pdn_uart, step, spread_en, dir;
    uint8_t version;   /* 0x21 on a genuine TMC2209 */
} tmc2209_ioin_t;

tmc2209_ioin_t tmc2209_ioin_decode(uint32_t raw);

#define TMC2209_IOIN_VERSION 0x21u

/* Sign-extended fields that are not plain unsigned counts. */
int32_t tmc2209_vactual_decode(uint32_t raw);

/* ── Diagnostic-only decoders ───────────────────────────────────────────── */
/* These exist for the PC-side report, not for firmware decisions. Nothing in
   the control path should be reading them. */

/* NOT a current measurement. These are the entries the driver read out of its
   internal sine table for the microstep position it is presently at, unscaled
   by the current setting. A pure function of MSCNT: identical values whether
   the motor is spinning, stalled, or unplugged. Both fields are 9-bit signed,
   which is the only reason a decoder is worth having. */
typedef struct {
    int16_t cur_a;   /* -255..255 */
    int16_t cur_b;
} tmc2209_mscuract_t;

tmc2209_mscuract_t tmc2209_mscuract_decode(uint32_t raw);

typedef struct {
    uint8_t sum;     /* actual PWM duty StealthChop settled on */
    int16_t automatic; /* -255..255, signed amplitude correction */
} tmc2209_pwm_scale_t;

tmc2209_pwm_scale_t tmc2209_pwm_scale_decode(uint32_t raw);

typedef struct {
    uint8_t ofs_auto;
    uint8_t grad_auto;
} tmc2209_pwm_auto_t;

tmc2209_pwm_auto_t tmc2209_pwm_auto_decode(uint32_t raw);

#endif /* TMC2209_REG_H */
