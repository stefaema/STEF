/**
 * @file tmc2209_reg.h
 * @brief The register table, its classification, and the field codecs.
 *
 * Two independent questions are answered here and must be kept apart.
 *
 * Access (@ref TMC2209_ACC_R, @ref TMC2209_ACC_W) is the driver's. Eight
 * registers are write-only driver-side, so asking the device what they hold is
 * a question it cannot answer.
 *
 * Class (@ref tmc2209_class_t) is who can change the value, which decides
 * whether a remembered value is still true. It is a physical property of the
 * part, not a performance judgement: cache by ownership, never by cost.
 *
 * There is deliberately no reset-value column. See design.md §1.
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
    TMC2209_OTP_READ     = 0x05,
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
    TMC2209_MSCURACT     = 0x6B,
    TMC2209_CHOPCONF     = 0x6C,
    TMC2209_DRV_STATUS   = 0x6F,
    TMC2209_PWMCONF      = 0x70,
    TMC2209_PWM_SCALE    = 0x71,
    TMC2209_PWM_AUTO     = 0x72,
} tmc2209_reg_t;

/** Total slots. Kept under 32 so the validity bitmap is a single uint32_t. */
#define TMC2209_REG_COUNT   23
/** Registers a configuration must cover. See tmc2209_adopt(). */
#define TMC2209_OWNED_COUNT 10

/** What the driver permits. */
enum {
    TMC2209_ACC_R = 1U << 0,
    TMC2209_ACC_W = 1U << 1,
};

/** Who can change the value, and therefore whether it can be cached. */
typedef enum {
    /** Not in the table. */
    TMC2209_CLASS_UNKNOWN = 0,
    /** The driver or the outside world writes it. Poll; never cache. */
    TMC2209_CLASS_VOLATILE,
    /** Only the firmware writes it. Cacheable while the slot stays valid. */
    TMC2209_CLASS_OWNED,
    /** Nothing writes it in this design. Read once at adopt, cached after. */
    TMC2209_CLASS_CONSTANT,
} tmc2209_class_t;

/** Slot in the cache array, or -1 if the register is not in the table. */
int             tmc2209_reg_slot(tmc2209_reg_t reg);
/** Access flags, or 0 if the register is not in the table. */
uint8_t         tmc2209_reg_access(tmc2209_reg_t reg);
/** Class, or TMC2209_CLASS_UNKNOWN if the register is not in the table. */
tmc2209_class_t tmc2209_reg_class(tmc2209_reg_t reg);
/** Datasheet name, or "?" if the register is not in the table. */
const char     *tmc2209_reg_name(tmc2209_reg_t reg);

/* Slot-indexed accessors, for iterating the cache without a reverse lookup.
   Callers must keep slot in [0, TMC2209_REG_COUNT). */
tmc2209_reg_t   tmc2209_reg_at(int slot);
uint8_t         tmc2209_reg_access_at(int slot);
tmc2209_class_t tmc2209_reg_class_at(int slot);

/* ── Conditions ─────────────────────────────────────────────────────────── */

/**
 * @brief What tmc2209_poll_health() reports, as a bitmask.
 *
 * Conditions, not register contents: the caller asks whether the driver is
 * healthy without learning that brownout lives in GSTAT and overtemperature
 * lives in DRV_STATUS.
 *
 * The two halves behave differently in time, which the caller must know.
 * Latched conditions report that something *happened* and stay asserted until
 * tmc2209_clear_faults() acknowledges them. Live conditions report what is
 * *true now* and clear themselves when the situation passes.
 */
typedef enum {
    /* Latched in GSTAT. Set once, asserted until acknowledged. */
    TMC2209_DRIVER_RESET      = 1U << 0,  /**< GSTAT.reset: the driver restarted, so
                                               every register is back at its default
                                               and the configuration is gone */
    TMC2209_DRIVER_FAULT      = 1U << 1,  /**< GSTAT.drv_err */
    TMC2209_UNDERVOLTAGE      = 1U << 2,  /**< GSTAT.uv_cp, charge pump */

    /* Live in DRV_STATUS. True now; nothing to acknowledge. */
    TMC2209_OVERTEMP_WARNING  = 1U << 3,  /**< DRV_STATUS.otpw */
    TMC2209_OVERTEMP_SHUTDOWN = 1U << 4,  /**< DRV_STATUS.ot */
    TMC2209_SHORT_CIRCUIT     = 1U << 5,  /**< DRV_STATUS s2ga/s2gb/s2vsa/s2vsb */
    TMC2209_OPEN_LOAD         = 1U << 6,  /**< DRV_STATUS ola/olb. Also true at standstill */
    TMC2209_STANDSTILL        = 1U << 7,  /**< DRV_STATUS.stst */
} tmc2209_condition_t;

/** Conditions that latch, and are therefore the ones tmc2209_clear_faults() acts on. */
#define TMC2209_CONDITIONS_LATCHED                                       \
    ((uint32_t)TMC2209_DRIVER_RESET | (uint32_t)TMC2209_DRIVER_FAULT |   \
     (uint32_t)TMC2209_UNDERVOLTAGE)

/** Conditions that mean the output stage has a real problem. */
#define TMC2209_CONDITIONS_FAULT                                        \
    ((uint32_t)TMC2209_DRIVER_FAULT | (uint32_t)TMC2209_UNDERVOLTAGE |  \
     (uint32_t)TMC2209_OVERTEMP_SHUTDOWN | (uint32_t)TMC2209_SHORT_CIRCUIT)

/** What tmc2209_poll_load() reports. */
typedef struct {
    uint16_t value;    /**< SG_RESULT, 0..510. Higher means less load */
    bool     usable;   /**< false when the reading carries no information */
} tmc2209_load_t;

/* ── Field enums ────────────────────────────────────────────────────────── */

typedef enum {
    TMC2209_MRES_256 = 0, TMC2209_MRES_128, TMC2209_MRES_64, TMC2209_MRES_32,
    TMC2209_MRES_16,      TMC2209_MRES_8,   TMC2209_MRES_4,  TMC2209_MRES_2,
    TMC2209_MRES_FULL,
} tmc2209_mres_t;

/** Microsteps per full step, for the rate arithmetic the actuator layer needs. */
uint16_t tmc2209_mres_microsteps(tmc2209_mres_t mres);

typedef enum { TMC2209_TBL_16 = 0, TMC2209_TBL_24, TMC2209_TBL_32, TMC2209_TBL_40 } tmc2209_tbl_t;
typedef enum { TMC2209_SEUP_1 = 0, TMC2209_SEUP_2, TMC2209_SEUP_4, TMC2209_SEUP_8 } tmc2209_seup_t;
typedef enum { TMC2209_SEDN_32 = 0, TMC2209_SEDN_8, TMC2209_SEDN_2, TMC2209_SEDN_1 } tmc2209_sedn_t;

/* ── Field codecs ───────────────────────────────────────────────────────── */

typedef struct {
    bool i_scale_analog;    /**< external VREF */
    bool internal_rsense;
    bool en_spreadcycle;    /**< 0 = StealthChop */
    bool shaft;             /**< invert direction */
    bool index_otpw;
    bool index_step;
    bool pdn_disable;       /**< 1 = PDN_UART is the UART pin. Required */
    bool mstep_reg_select;  /**< 1 = mres comes from CHOPCONF, not MS1/MS2. Required */
    bool multistep_filt;
    bool test_mode;         /**< factory use. Never set */
} tmc2209_gconf_t;

uint32_t        tmc2209_gconf_encode(const tmc2209_gconf_t *g);
tmc2209_gconf_t tmc2209_gconf_decode(uint32_t raw);

typedef struct {
    uint8_t        toff;    /**< 0 = driver disabled */
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
    uint8_t ihold;       /**< 0..31, holds film tension at rest */
    uint8_t irun;        /**< 0..31 */
    uint8_t iholddelay;  /**< 0..15 */
} tmc2209_ihold_irun_t;

uint32_t             tmc2209_ihold_irun_encode(const tmc2209_ihold_irun_t *i);
tmc2209_ihold_irun_t tmc2209_ihold_irun_decode(uint32_t raw);

typedef struct {
    uint8_t        semin;   /**< 0 = CoolStep off */
    tmc2209_seup_t seup;
    uint8_t        semax;
    tmc2209_sedn_t sedn;
    bool           seimin;
} tmc2209_coolconf_t;

uint32_t           tmc2209_coolconf_encode(const tmc2209_coolconf_t *c);
tmc2209_coolconf_t tmc2209_coolconf_decode(uint32_t raw);

typedef struct {
    bool    otpw, ot;             /**< overtemperature warning / shutdown */
    bool    s2ga, s2gb;           /**< short to ground */
    bool    s2vsa, s2vsb;         /**< short to supply */
    bool    ola, olb;             /**< open load */
    bool    t120, t143, t150, t157;
    uint8_t cs_actual;            /**< 0..31, the current the driver settled on */
    bool    stealth;
    bool    stst;                 /**< standstill */
} tmc2209_drv_status_t;

tmc2209_drv_status_t tmc2209_drv_status_decode(uint32_t raw);

typedef struct {
    bool reset;    /**< driver was reset and lost its configuration */
    bool drv_err;
    bool uv_cp;    /**< charge pump undervoltage */
} tmc2209_gstat_t;

uint32_t        tmc2209_gstat_encode(const tmc2209_gstat_t *g);  /**< write 1 to clear */
tmc2209_gstat_t tmc2209_gstat_decode(uint32_t raw);

/** The accepted-write counter, an 8-bit field that wraps. */
uint8_t tmc2209_ifcnt_decode(uint32_t raw);

typedef struct {
    bool    enn, ms1, ms2, diag, pdn_uart, step, spread_en, dir;
    uint8_t version;   /**< 0x21 on a genuine TMC2209 */
} tmc2209_ioin_t;

tmc2209_ioin_t tmc2209_ioin_decode(uint32_t raw);

/* Driver revision byte in IOIN, fixed for the part: what this library was
   written and tested against. A TMC2208 reads 0x20. Overridable at build time
   for register-compatible siblings that identify differently. */
#ifndef TMC2209_IOIN_VERSION
#define TMC2209_IOIN_VERSION 0x21u
#endif

/* Sign-extended fields that are not plain unsigned counts. */
int32_t  tmc2209_vactual_decode(uint32_t raw);
uint32_t tmc2209_vactual_encode(int32_t v);

/* ── Diagnostic-only decoders ───────────────────────────────────────────── */
/* For the PC-side report. Nothing in the control path reads these. */

/**
 * NOT a current measurement. These are the entries the driver read out of its
 * internal sine table for the microstep position it is presently at, unscaled
 * by the current setting. A pure function of MSCNT: identical values whether
 * the motor is spinning, stalled, or unplugged. Both fields are 9-bit signed,
 * which is the only reason a decoder is worth having.
 */
typedef struct {
    int16_t cur_a;   /**< -255..255 */
    int16_t cur_b;
} tmc2209_mscuract_t;

tmc2209_mscuract_t tmc2209_mscuract_decode(uint32_t raw);

typedef struct {
    uint8_t sum;        /**< actual PWM duty StealthChop settled on */
    int16_t automatic;  /**< -255..255, signed amplitude correction */
} tmc2209_pwm_scale_t;

tmc2209_pwm_scale_t tmc2209_pwm_scale_decode(uint32_t raw);

typedef struct {
    uint8_t ofs_auto;
    uint8_t grad_auto;
} tmc2209_pwm_auto_t;

tmc2209_pwm_auto_t tmc2209_pwm_auto_decode(uint32_t raw);

#endif /* TMC2209_REG_H */
