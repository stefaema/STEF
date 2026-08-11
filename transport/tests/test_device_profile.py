import pytest

from shared import fw_api
from transport import device_profile

SHIPPED = "capstan_base"


def base():
    return device_profile.load(SHIPPED)


def valued(ops):
    return {device_profile.register_name(op.reg): op.value for op in ops}


# ── What a profile has to cover ──────────────────────────────────────────────


def test_the_shipped_profile_covers_every_owned_register():
    written = valued(device_profile.ops(base()))

    assert set(written) == {
        "GCONF",
        "SLAVECONF",
        "IHOLD_IRUN",
        "TPOWERDOWN",
        "TPWMTHRS",
        "TCOOLTHRS",
        "VACTUAL",
        "SGTHRS",
        "COOLCONF",
        "CHOPCONF",
    }


def test_a_profile_missing_a_register_names_the_one_it_missed():
    profile = base()
    del profile["chopconf"]

    with pytest.raises(device_profile.ProfileError, match="names no chopconf"):
        device_profile.ops(profile)


def test_a_register_nothing_owns_is_refused_by_name():
    profile = base() | {"drv_status": {"value": 0}}

    with pytest.raises(device_profile.ProfileError, match="called drv_status"):
        device_profile.ops(profile)


# ── What the fields encode to ────────────────────────────────────────────────


def test_a_named_field_reaches_the_wire_as_the_codec_packs_it():
    written = valued(device_profile.ops(base()))

    gconf = fw_api.tmc2209_gconf_decode(written["GCONF"])
    assert gconf.pdn_disable and gconf.mstep_reg_select
    assert not gconf.en_spreadcycle

    chopconf = fw_api.tmc2209_chopconf_decode(written["CHOPCONF"])
    assert chopconf.toff == 3
    assert chopconf.mres == fw_api.TMC2209_MRES_16

    current = fw_api.tmc2209_ihold_irun_decode(written["IHOLD_IRUN"])
    assert (current.ihold, current.irun, current.iholddelay) == (8, 16, 8)


def test_a_scalar_register_carries_the_number_it_was_given():
    written = valued(device_profile.ops(base()))

    assert written["SLAVECONF"] == 0x200
    assert written["TPOWERDOWN"] == 20
    assert written["SGTHRS"] == 80
    assert written["VACTUAL"] == 0


def test_a_field_the_register_cannot_hold_is_refused_rather_than_truncated():
    profile = base()
    profile["ihold_irun"]["irun"] = 300

    with pytest.raises(device_profile.ProfileError, match="does not hold 300"):
        device_profile.ops(profile)


def test_a_flag_given_a_number_is_refused():
    profile = base()
    profile["gconf"]["shaft"] = 1

    with pytest.raises(device_profile.ProfileError, match="true or false"):
        device_profile.ops(profile)


def test_a_field_the_register_does_not_have_is_refused_by_name():
    profile = base()
    profile["chopconf"]["tof"] = 3

    with pytest.raises(device_profile.ProfileError, match="chopconf has no field tof"):
        device_profile.ops(profile)


def test_a_scalar_register_takes_a_value_and_nothing_else():
    profile = base()
    profile["tpowerdown"] = {"delay": 20}

    with pytest.raises(device_profile.ProfileError, match="carries no delay"):
        device_profile.ops(profile)


def test_a_gconf_that_would_end_the_conversation_is_refused():
    profile = base()
    profile["gconf"]["pdn_disable"] = False

    with pytest.raises(device_profile.ProfileError, match="leaves pdn_disable off"):
        device_profile.ops(profile)


# ── Naming what came back ────────────────────────────────────────────────────


def test_a_slot_mask_reads_as_the_registers_it_stands_for():
    slots = 1 << fw_api.tmc2209_reg_slot(fw_api.TMC2209_GCONF)
    slots |= 1 << fw_api.tmc2209_reg_slot(fw_api.TMC2209_CHOPCONF)

    assert device_profile.slot_names(slots) == ("GCONF", "CHOPCONF")
