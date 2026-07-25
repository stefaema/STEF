#include "tmc2209_reg.h"

#include <stddef.h>

#define R      TMC2209_ACC_R
#define W      TMC2209_ACC_W
#define CFG    TMC2209_ACC_CONFIG

typedef struct {
    tmc2209_reg_t reg;
    uint8_t       access;
    uint32_t      reset;
    const char   *name;
} reg_info_t;

/* Order defines the shadow slot, and therefore the dirty bit. Reset values are
   the chip's power-on defaults, which is the correct seed because that is what
   the device holds before we impose anything. */
static const reg_info_t k_regs[TMC2209_REG_COUNT] = {
    { TMC2209_GCONF,        R | W | CFG, 0x00000101u, "GCONF"        },
    /* The reset flag is set at power-on: the chip's way of saying it came up
       holding defaults, which is exactly what this column describes. */
    { TMC2209_GSTAT,        R | W,       0x00000001u, "GSTAT"        },
    { TMC2209_IFCNT,        R,           0x00000000u, "IFCNT"        },
    { TMC2209_SLAVECONF,        W | CFG, 0x00000000u, "SLAVECONF"    },
    { TMC2209_IOIN,         R,           0x00000000u, "IOIN"         },
    
    /* FACTORY_CONF is R/W in silicon but read-only to us*/
    { TMC2209_FACTORY_CONF, R,           0x00000000u, "FACTORY_CONF" },

    { TMC2209_IHOLD_IRUN,       W | CFG, 0x00071703u, "IHOLD_IRUN"   },
    { TMC2209_TPOWERDOWN,       W | CFG, 0x00000014u, "TPOWERDOWN"   },
    { TMC2209_TSTEP,        R,           0x000FFFFFu, "TSTEP"        },
    { TMC2209_TPWMTHRS,         W | CFG, 0x00000000u, "TPWMTHRS"     },
    { TMC2209_TCOOLTHRS,        W | CFG, 0x00000000u, "TCOOLTHRS"    },
    { TMC2209_VACTUAL,          W | CFG, 0x00000000u, "VACTUAL"      },
    { TMC2209_SGTHRS,           W | CFG, 0x00000000u, "SGTHRS"       },
    { TMC2209_SG_RESULT,    R,           0x00000000u, "SG_RESULT"    },
    { TMC2209_COOLCONF,         W | CFG, 0x00000000u, "COOLCONF"     },
    { TMC2209_MSCNT,        R,           0x00000000u, "MSCNT"        },
    { TMC2209_CHOPCONF,     R | W | CFG, 0x10000053u, "CHOPCONF"     },
    { TMC2209_DRV_STATUS,   R,           0x00000000u, "DRV_STATUS"   },

    /* Readable, never configured. Reachable so the diagnostic can see the
       whole device; carrying no CONFIG flag so they stay out of reflush.
       PWMCONF is R/W in silicon, but pwm_autoscale and pwm_autograd tune it
       better than we would, so our policy makes it read-only. */
    { TMC2209_OTP_READ,     R,           0x00000000u, "OTP_READ"     },
    { TMC2209_MSCURACT,     R,           0x00000000u, "MSCURACT"     },
    { TMC2209_PWMCONF,      R,           0xC10D0024u, "PWMCONF"      },
    { TMC2209_PWM_SCALE,    R,           0x00000000u, "PWM_SCALE"    },
    { TMC2209_PWM_AUTO,     R,           0x00000000u, "PWM_AUTO"     },
};

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
    return (slot < 0) ? 0u : k_regs[slot].access;
}

uint32_t tmc2209_reg_reset_value(tmc2209_reg_t reg)
{
    int slot = tmc2209_reg_slot(reg);
    return (slot < 0) ? 0u : k_regs[slot].reset;
}

const char *tmc2209_reg_name(tmc2209_reg_t reg)
{
    int slot = tmc2209_reg_slot(reg);
    return (slot < 0) ? "?" : k_regs[slot].name;
}

/* Used by tmc2209.c to seed the shadow and to build the reflush set. */
uint32_t tmc2209_reg_reset_at(int slot) { return k_regs[slot].reset; }
uint8_t  tmc2209_reg_access_at(int slot) { return k_regs[slot].access; }
tmc2209_reg_t tmc2209_reg_at(int slot) { return k_regs[slot].reg; }

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

#define BIT(v, n)  (((v) >> (n)) & 1u)

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
    return ((uint32_t)(c->toff  & 0x0Fu))        |
           ((uint32_t)(c->hstrt & 0x07u) << 4)   |
           ((uint32_t)(c->hend  & 0x0Fu) << 7)   |
           ((uint32_t)(c->tbl   & 0x03u) << 15)  |
           ((uint32_t)c->vsense          << 17)  |
           ((uint32_t)(c->mres  & 0x0Fu) << 24)  |
           ((uint32_t)c->intpol          << 28)  |
           ((uint32_t)c->dedge           << 29)  |
           ((uint32_t)c->diss2g          << 30)  |
           ((uint32_t)c->diss2vs         << 31);
}

tmc2209_chopconf_t tmc2209_chopconf_decode(uint32_t raw)
{
    tmc2209_chopconf_t c = {
        .toff    = (uint8_t)(raw & 0x0Fu),
        .hstrt   = (uint8_t)((raw >> 4) & 0x07u),
        .hend    = (uint8_t)((raw >> 7) & 0x0Fu),
        .tbl     = (tmc2209_tbl_t)((raw >> 15) & 0x03u),
        .vsense  = BIT(raw, 17),
        .mres    = (tmc2209_mres_t)((raw >> 24) & 0x0Fu),
        .intpol  = BIT(raw, 28),
        .dedge   = BIT(raw, 29),
        .diss2g  = BIT(raw, 30),
        .diss2vs = BIT(raw, 31),
    };
    return c;
}

uint32_t tmc2209_ihold_irun_encode(const tmc2209_ihold_irun_t *i)
{
    return ((uint32_t)(i->ihold      & 0x1Fu))       |
           ((uint32_t)(i->irun       & 0x1Fu) << 8)  |
           ((uint32_t)(i->iholddelay & 0x0Fu) << 16);
}

tmc2209_ihold_irun_t tmc2209_ihold_irun_decode(uint32_t raw)
{
    tmc2209_ihold_irun_t i = {
        .ihold      = (uint8_t)(raw & 0x1Fu),
        .irun       = (uint8_t)((raw >> 8) & 0x1Fu),
        .iholddelay = (uint8_t)((raw >> 16) & 0x0Fu),
    };
    return i;
}

uint32_t tmc2209_coolconf_encode(const tmc2209_coolconf_t *c)
{
    return ((uint32_t)(c->semin & 0x0Fu))        |
           ((uint32_t)(c->seup  & 0x03u) << 5)   |
           ((uint32_t)(c->semax & 0x0Fu) << 8)   |
           ((uint32_t)(c->sedn  & 0x03u) << 13)  |
           ((uint32_t)c->seimin          << 15);
}

tmc2209_coolconf_t tmc2209_coolconf_decode(uint32_t raw)
{
    tmc2209_coolconf_t c = {
        .semin  = (uint8_t)(raw & 0x0Fu),
        .seup   = (tmc2209_seup_t)((raw >> 5) & 0x03u),
        .semax  = (uint8_t)((raw >> 8) & 0x0Fu),
        .sedn   = (tmc2209_sedn_t)((raw >> 13) & 0x03u),
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
        .cs_actual = (uint8_t)((raw >> 16) & 0x1Fu),
        .stealth   = BIT(raw, 30),
        .stst      = BIT(raw, 31),
    };
    return s;
}

bool tmc2209_drv_status_faulted(const tmc2209_drv_status_t *s)
{
    /* Open load is deliberately excluded: it reads true at standstill and at
       low current, so treating it as a fault would trip on healthy motors. */
    return s->ot || s->s2ga || s->s2gb || s->s2vsa || s->s2vsb;
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
    return (uint8_t)raw;   /* low byte; the chip reads the rest back as zero */
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
        .version   = (uint8_t)((raw >> 24) & 0xFFu),
    };
    return i;
}

int32_t tmc2209_vactual_decode(uint32_t raw)
{
    uint32_t v = raw & 0x00FFFFFFu;
    if (v & (1u << 23)) {
        v |= 0xFF000000u;   /* sign-extend the 24-bit field */
    }
    return (int32_t)v;
}

/* ── Diagnostic-only decoders ───────────────────────────────────────────── */

/* 9-bit two's complement, which is the awkward part and the reason these
   registers get decoders at all. */
static int16_t sign_extend_9(uint32_t field)
{
    uint32_t v = field & 0x1FFu;
    if (v & (1u << 8)) {
        v |= 0xFFFFFE00u;
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
        .sum       = (uint8_t)(raw & 0xFFu),
        .automatic = sign_extend_9(raw >> 16),
    };
    return p;
}

tmc2209_pwm_auto_t tmc2209_pwm_auto_decode(uint32_t raw)
{
    tmc2209_pwm_auto_t p = {
        .ofs_auto  = (uint8_t)(raw & 0xFFu),
        .grad_auto = (uint8_t)((raw >> 16) & 0xFFu),
    };
    return p;
}
