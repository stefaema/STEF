from __future__ import annotations

import ctypes
from typing import Any

from shared import config, fw_api

PACKAGE = "transport"
DIRECTORY = "devices"
SCALAR = "value"

REQUIRED_GCONF = ("pdn_disable", "mstep_reg_select")

CODECS: dict[str, tuple[Any, Any]] = {
    "gconf": (fw_api.tmc2209_gconf_t, fw_api.tmc2209_gconf_encode),
    "chopconf": (fw_api.tmc2209_chopconf_t, fw_api.tmc2209_chopconf_encode),
    "ihold_irun": (fw_api.tmc2209_ihold_irun_t, fw_api.tmc2209_ihold_irun_encode),
    "coolconf": (fw_api.tmc2209_coolconf_t, fw_api.tmc2209_coolconf_encode),
}

SIGNED = {"vactual": fw_api.tmc2209_vactual_encode}


class ProfileError(Exception):
    pass


def owned() -> dict[str, int]:
    return {
        fw_api.tmc2209_reg_name(int(reg)).decode().lower(): int(reg)
        for reg in fw_api.Tmc2209Reg
        if fw_api.tmc2209_reg_class(int(reg)) == fw_api.TMC2209_CLASS_OWNED
    }


def register_name(reg: int) -> str:
    return fw_api.tmc2209_reg_name(int(reg)).decode()


def slot_names(mask: int) -> tuple[str, ...]:
    return tuple(
        register_name(fw_api.tmc2209_reg_at(slot))
        for slot in range(fw_api.TMC2209_REG_COUNT)
        if mask & (1 << slot)
    )


# ── What there is to bring a device up with ──────────────────────────────────


def names() -> tuple[str, ...]:
    return config.available(PACKAGE, DIRECTORY)


def load(name: str) -> dict[str, Any]:
    return config.get(PACKAGE, DIRECTORY, f"{name}{config.SUFFIX}")


# ── The ten registers it stands for ──────────────────────────────────────────


def ops(profile: dict[str, Any]) -> tuple[Any, ...]:
    """Return the ten register writes a bring-up covers, in order."""
    wanted = owned()
    unknown = sorted(set(profile) - set(wanted))
    if unknown:
        raise ProfileError(
            f"no owned register is called {', '.join(unknown)}; "
            f"the ten are {', '.join(wanted)}"
        )
    missing = sorted(set(wanted) - set(profile))
    if missing:
        raise ProfileError(
            f"a bring-up covers every owned register and this names no "
            f"{', '.join(missing)}"
        )

    op = fw_api.dataclass_for(fw_api.rpc_op_t)
    return tuple(
        op(value=value_of(name, profile[name]), reg=reg) for name, reg in wanted.items()
    )


def value_of(name: str, written: Any) -> int:
    """Return the number to write for one register, given what the profile says about it."""
    if name in CODECS:
        struct_type, encode = CODECS[name]
        return int(encode(ctypes.byref(_filled(name, struct_type, written))))
    return _one_number(name, written)


def _one_number(name: str, written: Any) -> int:
    """Return the number a scalar register's table holds, refusing any other shape."""
    if not isinstance(written, dict):
        raise ProfileError(
            f"write [{name}] with {SCALAR} = {written!r} on the line below it; "
            f"every owned register is a table, even the ones holding one number"
        )

    unknown = sorted(set(written) - {SCALAR})
    if unknown:
        raise ProfileError(
            f"{name} is one number under {SCALAR!r} and carries no {', '.join(unknown)}"
        )
    if SCALAR not in written:
        raise ProfileError(f"{name} names no {SCALAR}")

    number = _as_number(name, SCALAR, written[SCALAR])
    if name in SIGNED:
        return int(SIGNED[name](number))
    if number < 0:
        raise ProfileError(f"{name} is {number}, and the register holds no sign")
    return number


def _filled(name: str, struct_type: Any, written: dict[str, Any]) -> Any:
    declared = {field: ctype for field, ctype, *_ in struct_type._fields_}
    unknown = sorted(set(written) - set(declared))
    if unknown:
        raise ProfileError(
            f"{name} has no field {', '.join(unknown)}; it has {', '.join(declared)}"
        )
    if name == "gconf":
        _refuse_unreachable(written)

    built = struct_type()
    for field, value in written.items():
        setattr(built, field, _as_declared(name, field, declared[field], value))
        if getattr(built, field) != value:
            raise ProfileError(
                f"{name}.{field} does not hold {value!r}; the register keeps "
                f"{getattr(built, field)!r} of it"
            )
    return built


def _as_declared(name: str, field: str, ctype: Any, value: Any) -> Any:
    if ctype is ctypes.c_bool:
        if not isinstance(value, bool):
            raise ProfileError(f"{name}.{field} is true or false, not {value!r}")
        return value
    return _as_number(name, field, value)


def _as_number(name: str, field: str, value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProfileError(f"{name}.{field} is a number, not {value!r}")
    return value


def _refuse_unreachable(written: dict[str, Any]) -> None:
    off = [field for field in REQUIRED_GCONF if not written.get(field)]
    if off:
        raise ProfileError(
            f"gconf leaves {', '.join(off)} off, which takes the driver off the "
            f"UART or off CHOPCONF's mres. Nothing could be written after it"
        )
