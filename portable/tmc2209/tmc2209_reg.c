#include "tmc2209_reg.h"

#include <stddef.h>

/* clang-format off */
#define R  TMC2209_ACCESS_READ
#define W  TMC2209_ACCESS_WRITE

#define VOL TMC2209_CLASS_VOLATILE
#define OWN TMC2209_CLASS_OWNED
#define CST TMC2209_CLASS_CONSTANT

typedef struct {
    tmc2209_reg_t   reg;
    uint8_t         access;   /* what the driver permits */
    tmc2209_class_t cls;      /* who can change the value */
    const char     *name;
} reg_info_t;

/* Order defines the cache slot, and therefore the validity bit.
 *
 * Access and class are independent. VACTUAL is write-only driver-side yet
 * OWNED, because the driver refusing to read it back says nothing about who
 * changes it. GSTAT is readable and writable yet VOLATILE, because the
 * hardware sets its flags. Getting those two backwards is the bug this column
 * exists to prevent.
 */
static const reg_info_t k_regs[TMC2209_REG_COUNT] = {
    { TMC2209_GCONF,        R | W, OWN, "GCONF"        },
    { TMC2209_GSTAT,        R | W, VOL, "GSTAT"        },  /* hardware latches the flags */
    { TMC2209_IFCNT,        R,     VOL, "IFCNT"        },  /* hardware increments it */
    { TMC2209_SLAVECONF,        W, OWN, "SLAVECONF"    },
    { TMC2209_IOIN,         R,     VOL, "IOIN"         },  /* live pin state */
    { TMC2209_FACTORY_CONF, R,     CST, "FACTORY_CONF" },  /* never written: holds the trim */
    { TMC2209_IHOLD_IRUN,       W, OWN, "IHOLD_IRUN"   },
    { TMC2209_TPOWERDOWN,       W, OWN, "TPOWERDOWN"   },
    { TMC2209_TSTEP,        R,     VOL, "TSTEP"        },  /* the driver measures it, time btwn steps */
    { TMC2209_TPWMTHRS,         W, OWN, "TPWMTHRS"     },
    { TMC2209_TCOOLTHRS,        W, OWN, "TCOOLTHRS"    },
    { TMC2209_VACTUAL,          W, OWN, "VACTUAL"      },
    { TMC2209_SGTHRS,           W, OWN, "SGTHRS"       },
    { TMC2209_SG_RESULT,    R,     VOL, "SG_RESULT"    },  /* back-EMF estimate */
    { TMC2209_COOLCONF,         W, OWN, "COOLCONF"     },
    { TMC2209_MSCNT,        R,     VOL, "MSCNT"        },  /* advances with steps */
    { TMC2209_CHOPCONF,     R | W, OWN, "CHOPCONF"     },
    { TMC2209_DRV_STATUS,   R,     VOL, "DRV_STATUS"   },

    /* Never written by policy, and nothing else writes them either, so their
       value is knowable after one read. PWMCONF is R/W driver-side; autoscale
       and autograd tune PWM_SCALE and PWM_AUTO instead of touching it. */
    { TMC2209_OTP_READ,     R,     CST, "OTP_READ"     },
    { TMC2209_PWMCONF,      R,     CST, "PWMCONF"      },

    /* Diagnostic only. No firmware decision depends on these. */
    { TMC2209_MSCURACT,     R,     VOL, "MSCURACT"     },
    { TMC2209_PWM_SCALE,    R,     VOL, "PWM_SCALE"    },
    { TMC2209_PWM_AUTO,     R,     VOL, "PWM_AUTO"     },
};
/* clang-format on */

int tmc2209_reg_slot(tmc2209_reg_t reg)
{
    for (int i = 0; i < TMC2209_REG_COUNT; i++) {
        if (k_regs[i].reg == reg) {
            return i;
        }
    }
    return -1;
}

uint8_t tmc2209_reg_access(tmc2209_reg_t reg)
{
    int slot = tmc2209_reg_slot(reg);
    return (slot < 0) ? 0U : k_regs[slot].access;
}

tmc2209_class_t tmc2209_reg_class(tmc2209_reg_t reg)
{
    int slot = tmc2209_reg_slot(reg);
    return (slot < 0) ? TMC2209_CLASS_UNKNOWN : k_regs[slot].cls;
}

const char *tmc2209_reg_name(tmc2209_reg_t reg)
{
    int slot = tmc2209_reg_slot(reg);
    return (slot < 0) ? "?" : k_regs[slot].name;
}

/* clang-format off */
uint8_t         tmc2209_reg_access_at(int slot) { return k_regs[slot].access; }
tmc2209_class_t tmc2209_reg_class_at(int slot)  { return k_regs[slot].cls; }
tmc2209_reg_t   tmc2209_reg_at(int slot)        { return k_regs[slot].reg; }

/* ── Field codecs ───────────────────────────────────────────────────────── */

uint16_t tmc2209_mres_microsteps(tmc2209_mres_t mres)
{
    switch (mres) {
    case TMC2209_MRES_256:  return 256;
    case TMC2209_MRES_128:  return 128;
    case TMC2209_MRES_64:   return 64;
    case TMC2209_MRES_32:   return 32;
    case TMC2209_MRES_16:   return 16;
    case TMC2209_MRES_8:    return 8;
    case TMC2209_MRES_4:    return 4;
    case TMC2209_MRES_2:    return 2;
    case TMC2209_MRES_FULL: return 1;
    }
    return 0;
}

#define BIT(v, n)  (((v) >> (n)) & 1U)

uint32_t tmc2209_gconf_encode(const tmc2209_gconf_t *g)
{
    return ((uint32_t)g->i_scale_analog   << 0) |
           ((uint32_t)g->internal_rsense  << 1) |
           ((uint32_t)g->en_spreadcycle   << 2) |
           ((uint32_t)g->shaft            << 3) |
           ((uint32_t)g->index_otpw       << 4) |
           ((uint32_t)g->index_step       << 5) |
           ((uint32_t)g->pdn_disable      << 6) |
           ((uint32_t)g->mstep_reg_select << 7) |
           ((uint32_t)g->multistep_filt   << 8) |
           ((uint32_t)g->test_mode        << 9);
}

tmc2209_gconf_t tmc2209_gconf_decode(uint32_t raw)
{
    tmc2209_gconf_t g = {
        .i_scale_analog   = BIT(raw, 0),
        .internal_rsense  = BIT(raw, 1),
        .en_spreadcycle   = BIT(raw, 2),
        .shaft            = BIT(raw, 3),
        .index_otpw       = BIT(raw, 4),
        .index_step       = BIT(raw, 5),
        .pdn_disable      = BIT(raw, 6),
        .mstep_reg_select = BIT(raw, 7),
        .multistep_filt   = BIT(raw, 8),
        .test_mode        = BIT(raw, 9),
    };
    return g;
}

uint32_t tmc2209_chopconf_encode(const tmc2209_chopconf_t *c)
{
    return ((uint32_t)(c->toff  & 0x0FU))        |
           ((uint32_t)(c->hstrt & 0x07U) << 4)   |
           ((uint32_t)(c->hend  & 0x0FU) << 7)   |
           ((uint32_t)(c->tbl   & 0x03U) << 15)  |
           ((uint32_t)c->vsense          << 17)  |
           ((uint32_t)(c->mres  & 0x0FU) << 24)  |
           ((uint32_t)c->intpol          << 28)  |
           ((uint32_t)c->dedge           << 29)  |
           ((uint32_t)c->diss2g          << 30)  |
           ((uint32_t)c->diss2vs         << 31);
}

tmc2209_chopconf_t tmc2209_chopconf_decode(uint32_t raw)
{
    tmc2209_chopconf_t c = {
        .toff    = (uint8_t)(raw & 0x0FU),
        .hstrt   = (uint8_t)((raw >> 4) & 0x07U),
        .hend    = (uint8_t)((raw >> 7) & 0x0FU),
        .tbl     = (tmc2209_tbl_t)((raw >> 15) & 0x03U),
        .vsense  = BIT(raw, 17),
        .mres    = (tmc2209_mres_t)((raw >> 24) & 0x0FU),
        .intpol  = BIT(raw, 28),
        .dedge   = BIT(raw, 29),
        .diss2g  = BIT(raw, 30),
        .diss2vs = BIT(raw, 31),
    };
    return c;
}

uint32_t tmc2209_ihold_irun_encode(const tmc2209_ihold_irun_t *i)
{
    return ((uint32_t)(i->ihold      & 0x1FU))       |
           ((uint32_t)(i->irun       & 0x1FU) << 8)  |
           ((uint32_t)(i->iholddelay & 0x0FU) << 16);
}

tmc2209_ihold_irun_t tmc2209_ihold_irun_decode(uint32_t raw)
{
    tmc2209_ihold_irun_t i = {
        .ihold      = (uint8_t)(raw & 0x1FU),
        .irun       = (uint8_t)((raw >> 8) & 0x1FU),
        .iholddelay = (uint8_t)((raw >> 16) & 0x0FU),
    };
    return i;
}

uint32_t tmc2209_coolconf_encode(const tmc2209_coolconf_t *c)
{
    return ((uint32_t)(c->semin & 0x0FU))        |
           ((uint32_t)(c->seup  & 0x03U) << 5)   |
           ((uint32_t)(c->semax & 0x0FU) << 8)   |
           ((uint32_t)(c->sedn  & 0x03U) << 13)  |
           ((uint32_t)c->seimin          << 15);
}

tmc2209_coolconf_t tmc2209_coolconf_decode(uint32_t raw)
{
    tmc2209_coolconf_t c = {
        .semin  = (uint8_t)(raw & 0x0FU),
        .seup   = (tmc2209_seup_t)((raw >> 5) & 0x03U),
        .semax  = (uint8_t)((raw >> 8) & 0x0FU),
        .sedn   = (tmc2209_sedn_t)((raw >> 13) & 0x03U),
        .seimin = BIT(raw, 15),
    };
    return c;
}

tmc2209_drv_status_t tmc2209_drv_status_decode(uint32_t raw)
{
    tmc2209_drv_status_t s = {
        .otpw      = BIT(raw, 0),
        .ot        = BIT(raw, 1),
        .s2ga      = BIT(raw, 2),
        .s2gb      = BIT(raw, 3),
        .s2vsa     = BIT(raw, 4),
        .s2vsb     = BIT(raw, 5),
        .ola       = BIT(raw, 6),
        .olb       = BIT(raw, 7),
        .t120      = BIT(raw, 8),
        .t143      = BIT(raw, 9),
        .t150      = BIT(raw, 10),
        .t157      = BIT(raw, 11),
        .cs_actual = (uint8_t)((raw >> 16) & 0x1FU),
        .stealth   = BIT(raw, 30),
        .stst      = BIT(raw, 31),
    };
    return s;
}

uint32_t tmc2209_gstat_encode(const tmc2209_gstat_t *g)
{
    return ((uint32_t)g->reset   << 0) |
           ((uint32_t)g->drv_err << 1) |
           ((uint32_t)g->uv_cp   << 2);
}

tmc2209_gstat_t tmc2209_gstat_decode(uint32_t raw)
{
    tmc2209_gstat_t g = {
        .reset   = BIT(raw, 0),
        .drv_err = BIT(raw, 1),
        .uv_cp   = BIT(raw, 2),
    };
    return g;
}

uint8_t tmc2209_ifcnt_decode(uint32_t raw)
{
    return (uint8_t)raw;   /* low byte; the driver reads the rest back as zero */
}

tmc2209_ioin_t tmc2209_ioin_decode(uint32_t raw)
{
    tmc2209_ioin_t i = {
        .enn       = BIT(raw, 0),
        .ms1       = BIT(raw, 2),
        .ms2       = BIT(raw, 3),
        .diag      = BIT(raw, 4),
        .pdn_uart  = BIT(raw, 6),
        .step      = BIT(raw, 7),
        .spread_en = BIT(raw, 8),
        .dir       = BIT(raw, 9),
        .version   = (uint8_t)((raw >> 24) & 0xFFU),
    };
    return i;
}

int32_t tmc2209_vactual_decode(uint32_t raw)
{
    uint32_t v = raw & 0x00FFFFFFU;
    if (v & (1U << 23)) {
        v |= 0xFF000000U;   /* sign-extend the 24-bit field */
    }
    return (int32_t)v;
}

uint32_t tmc2209_vactual_encode(int32_t v)
{
    return (uint32_t)v & 0x00FFFFFFU;   /* truncate to the 24-bit field */
}

/* ── Diagnostic-only decoders ───────────────────────────────────────────── */

/* 9-bit two's complement, which is the awkward part and the reason these
   registers get decoders at all. */
static int16_t sign_extend_9(uint32_t field)
{
    uint32_t v = field & 0x1FFU;
    if (v & (1U << 8)) {
        v |= 0xFFFFFE00U;
    }
    return (int16_t)(int32_t)v;
}

tmc2209_mscuract_t tmc2209_mscuract_decode(uint32_t raw)
{
    tmc2209_mscuract_t m = {
        .cur_a = sign_extend_9(raw),
        .cur_b = sign_extend_9(raw >> 16),
    };
    return m;
}

tmc2209_pwm_scale_t tmc2209_pwm_scale_decode(uint32_t raw)
{
    tmc2209_pwm_scale_t p = {
        .sum       = (uint8_t)(raw & 0xFFU),
        .automatic = sign_extend_9(raw >> 16),
    };
    return p;
}

tmc2209_pwm_auto_t tmc2209_pwm_auto_decode(uint32_t raw)
{
    tmc2209_pwm_auto_t p = {
        .ofs_auto  = (uint8_t)(raw & 0xFFU),
        .grad_auto = (uint8_t)((raw >> 16) & 0xFFU),
    };
    return p;
}
