/**
 * @file tmc2209_reg.h
 * @brief The register table, its classification, and the field codecs.
 *
 * Two independent questions are answered here and must be kept apart.
 *
 * Access (@ref TMC2209_ACCESS_READ, @ref TMC2209_ACCESS_WRITE) is the driver's.
 * Eight registers are write-only driver-side, so asking the device what they
 * hold is a question it cannot answer.
 *
 * Class (@ref tmc2209_class_t) is who can change the value, which decides
 * whether a remembered value is still true.
 *
 */

#ifndef TMC2209_REG_H
#define TMC2209_REG_H

#include <stdbool.h>
#include <stdint.h>

/** @brief Every register the library knows, by its datasheet address. */
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

/** Registers in the table, and therefore cache slots. OTP_PROG is excluded: it blows fuses. */
#define TMC2209_REG_COUNT   23
/** Registers whose modification should be exclusive to the library. */
#define TMC2209_OWNED_COUNT 10

/** @brief What the driver permits, as a bitmask. */
enum {
    TMC2209_ACCESS_READ  = 1U << 0,  /**< the register can be read back */
    TMC2209_ACCESS_WRITE = 1U << 1,  /**< the register can be written */
};

/** Who changes the value, and therefore whether it can be cached. */
typedef enum {
    /** Not in the table. */
    TMC2209_CLASS_UNKNOWN = 0,
    /** The driver itself writes the register. Poll; never cache. */
    TMC2209_CLASS_VOLATILE,
    /** Only the firmware writes to this register. Cacheable while the slot stays valid. */
    TMC2209_CLASS_OWNED,
    /** Nothing writes to this register in this design. Read once at bring-up, cached after. */
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

/**
 * @name Slot-indexed accessors
 * For iterating the cache without a reverse lookup.
 * Callers must keep slot in [0, TMC2209_REG_COUNT).
 * @{
 */
tmc2209_reg_t   tmc2209_reg_at(int slot);
uint8_t         tmc2209_reg_access_at(int slot);
tmc2209_class_t tmc2209_reg_class_at(int slot);
/** @} */

/* ── Conditions ─────────────────────────────────────────────────────────── */

/**
 * @brief What tmc2209_poll_health() reports, as a bitmask.
 *
 * The caller asks whether the driver is healthy without learning
 * that brownout lives in GSTAT and overtemperature lives in DRV_STATUS.
 *
 * The two halves behave differently in time, which the caller must know.
 * Latched conditions report that something *happened* and stay asserted until
 * tmc2209_clear_faults() acknowledges them. Live conditions report what is
 * *true now* and clear themselves when the situation passes.
 */
/* clang-format off */
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
/* clang-format on */

/** What tmc2209_poll_load() reports. */
typedef struct {
    uint16_t value;    /**< SG_RESULT, 0..510. Higher means less load */
    bool     usable;   /**< false when the reading carries no information */
} tmc2209_load_t;

/* ── Field enums ────────────────────────────────────────────────────────── */

/** @brief CHOPCONF.mres, named for the microstep count and not the raw code. */
typedef enum {
    /* clang-format off */
    TMC2209_MRES_256 = 0, TMC2209_MRES_128, TMC2209_MRES_64, TMC2209_MRES_32,
    TMC2209_MRES_16,      TMC2209_MRES_8,   TMC2209_MRES_4,  TMC2209_MRES_2,
    TMC2209_MRES_FULL,
    /* clang-format on */
} tmc2209_mres_t;

/** Microsteps per full step. */
uint16_t tmc2209_mres_microsteps(tmc2209_mres_t mres);

/** @brief CHOPCONF.tbl, comparator blank time in clock cycles. */
typedef enum { TMC2209_TBL_16 = 0, TMC2209_TBL_24, TMC2209_TBL_32, TMC2209_TBL_40 } tmc2209_tbl_t;
/** @brief COOLCONF.seup, current increment per step when load rises. */
typedef enum { TMC2209_SEUP_1 = 0, TMC2209_SEUP_2, TMC2209_SEUP_4, TMC2209_SEUP_8 } tmc2209_seup_t;
/** @brief COOLCONF.sedn, measurements per current decrement when load falls. */
typedef enum { TMC2209_SEDN_32 = 0, TMC2209_SEDN_8, TMC2209_SEDN_2, TMC2209_SEDN_1 } tmc2209_sedn_t;

/* ── Field codecs ───────────────────────────────────────────────────────── */

/** @brief GCONF, the global mode flags. */
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

/** @brief CHOPCONF, the chopper and microstep resolution settings. */
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

/** @brief IHOLD_IRUN, the run and hold current scalers. */
typedef struct {
    uint8_t ihold;       /**< 0..31 */
    uint8_t irun;        /**< 0..31 */
    uint8_t iholddelay;  /**< 0..15 */
} tmc2209_ihold_irun_t;

uint32_t             tmc2209_ihold_irun_encode(const tmc2209_ihold_irun_t *i);
tmc2209_ihold_irun_t tmc2209_ihold_irun_decode(uint32_t raw);

/** @brief COOLCONF, the CoolStep load-adaptive current thresholds. */
typedef struct {
    uint8_t        semin;   /**< 0 = CoolStep off */
    tmc2209_seup_t seup;
    uint8_t        semax;
    tmc2209_sedn_t sedn;
    bool           seimin;
} tmc2209_coolconf_t;

uint32_t           tmc2209_coolconf_encode(const tmc2209_coolconf_t *c);
tmc2209_coolconf_t tmc2209_coolconf_decode(uint32_t raw);

/** @brief DRV_STATUS, what the output stage reports right now. */
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

/** @brief GSTAT, the latched global faults. */
typedef struct {
    bool reset;    /**< driver was reset and lost its configuration */
    bool drv_err;
    bool uv_cp;    /**< charge pump undervoltage */
} tmc2209_gstat_t;

uint32_t        tmc2209_gstat_encode(const tmc2209_gstat_t *g);  /**< write 1 to clear */
tmc2209_gstat_t tmc2209_gstat_decode(uint32_t raw);

/** The accepted-write counter, an 8-bit field that wraps. */
uint8_t tmc2209_ifcnt_decode(uint32_t raw);

/** @brief IOIN, the live state of the driver's input pins. */
typedef struct {
    bool    enn, ms1, ms2, diag, pdn_uart, step, spread_en, dir;
    uint8_t version;   /**< revision byte, whatever the part answers */
} tmc2209_ioin_t;

tmc2209_ioin_t tmc2209_ioin_decode(uint32_t raw);

/**
 * Driver revision byte in IOIN: what this library was written and tested
 * against. A TMC2209 of a later revision is still a TMC2209,
 * so nothing here compares against this. It is published so a caller
 * that does want to demand the tested revision has the number to demand.
 */
#define TMC2209_LIB_IOIN_VERSION 0x21u

/** VACTUAL, a signed 24-bit velocity. Sign-extended, not a plain count. */
int32_t  tmc2209_vactual_decode(uint32_t raw);
uint32_t tmc2209_vactual_encode(int32_t v);

/* ── Diagnostic-only decoders ───────────────────────────────────────────── */

/**
 * @brief MSCURACT, the sine-table entries for the current microstep position.
 *
 * These are the entries the driver read out of its internal sine table for the
 * microstep position it is presently at, unscaled by the current setting.
 * A pure function of MSCNT: identical values whether the motor is spinning,
 * stalled, or unplugged. Both fields are 9-bit signed, which is the only reason
 * a decoder is worth having.
 */
typedef struct {
    int16_t cur_a;   /**< -255..255 */
    int16_t cur_b;
} tmc2209_mscuract_t;

tmc2209_mscuract_t tmc2209_mscuract_decode(uint32_t raw);

/** @brief PWM_SCALE, the duty StealthChop is currently applying. */
typedef struct {
    uint8_t sum;        /**< actual PWM duty StealthChop settled on */
    int16_t automatic;  /**< -255..255, signed amplitude correction */
} tmc2209_pwm_scale_t;

tmc2209_pwm_scale_t tmc2209_pwm_scale_decode(uint32_t raw);

/** @brief PWM_AUTO, the offset and gradient StealthChop tuned for itself. */
typedef struct {
    uint8_t ofs_auto;
    uint8_t grad_auto;
} tmc2209_pwm_auto_t;

tmc2209_pwm_auto_t tmc2209_pwm_auto_decode(uint32_t raw);

#endif /* TMC2209_REG_H */
