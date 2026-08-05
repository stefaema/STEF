"""Turns the firmware headers into fw_abi.py, the PC's view of the same ABI."""

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

import clang.cindex as cindex
from clang.cindex import CursorKind, TypeKind

T = TypeVar("T")

# ── What gets read ───────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = Path(__file__).resolve().parents[1]
OUT = PACKAGE / "fw_abi.py"

INCLUDE_DIRS = [
    ROOT / "rpc" / "include",
    ROOT / "shared" / "rpc_api" / "include",
    ROOT / "tmc2209" / "include",
]

TYPES_AND_FUNCTIONS = True
NAMES_ONLY = False

HEADERS = [
    ("rpc/include/rpc_proto.h", TYPES_AND_FUNCTIONS),
    ("rpc/include/rpc_frame.h", TYPES_AND_FUNCTIONS),
    ("rpc/include/cobs.h", TYPES_AND_FUNCTIONS),
    ("rpc/include/crc16.h", TYPES_AND_FUNCTIONS),
    ("shared/rpc_api/include/rpc_api.h", TYPES_AND_FUNCTIONS),
    ("tmc2209/include/tmc2209_err.h", TYPES_AND_FUNCTIONS),
    ("tmc2209/include/tmc2209_frame.h", TYPES_AND_FUNCTIONS),
    ("tmc2209/include/tmc2209_reg.h", TYPES_AND_FUNCTIONS),
    ("tmc2209/include/tmc2209_lines.h", NAMES_ONLY),
    ("tmc2209/include/tmc2209_stepgen.h", NAMES_ONLY),
]

STATUS_HEADERS = {"rpc_proto.h", "rpc_api.h"}
STATUS_NOT_A_VALUE = {"RPC_OK", "RPC_STATUS_LAST"}
COUNT_FIELD = "count"

# ── How a C type is spelled in ctypes ────────────────────────────────────────

STDINT = {
    "int8_t": "ctypes.c_int8",
    "int16_t": "ctypes.c_int16",
    "int32_t": "ctypes.c_int32",
    "int64_t": "ctypes.c_int64",
    "uint8_t": "ctypes.c_uint8",
    "uint16_t": "ctypes.c_uint16",
    "uint32_t": "ctypes.c_uint32",
    "uint64_t": "ctypes.c_uint64",
    "size_t": "ctypes.c_size_t",
}

PRIMITIVES = {
    TypeKind.BOOL: "ctypes.c_bool",
    TypeKind.CHAR_S: "ctypes.c_char",
    TypeKind.CHAR_U: "ctypes.c_char",
    TypeKind.SCHAR: "ctypes.c_byte",
    TypeKind.UCHAR: "ctypes.c_ubyte",
    TypeKind.SHORT: "ctypes.c_short",
    TypeKind.USHORT: "ctypes.c_ushort",
    TypeKind.INT: "ctypes.c_int",
    TypeKind.UINT: "ctypes.c_uint",
    TypeKind.LONG: "ctypes.c_long",
    TypeKind.ULONG: "ctypes.c_ulong",
    TypeKind.LONGLONG: "ctypes.c_longlong",
    TypeKind.ULONGLONG: "ctypes.c_ulonglong",
    TypeKind.FLOAT: "ctypes.c_float",
    TypeKind.DOUBLE: "ctypes.c_double",
}


# ── What one pass collects ───────────────────────────────────────────────────


class GeneratorError(Exception):
    """Anything that makes the headers unreadable or the output untrustworthy."""


@dataclass
class Record:
    """One struct or union, its fields already rendered as ctypes source."""

    name: str
    kind: str
    fields: list[tuple[str, str]]
    size: int
    flex: tuple[str, str, str] | None = None


@dataclass
class Enum:
    """One named C enum and the value of each enumerator."""

    name: str
    members: list[tuple[str, int]]


@dataclass
class Function:
    """One exported function, as the argtypes and restype ctypes needs."""

    name: str
    restype: str | None
    argtypes: list[str]


@dataclass
class Abi:
    """Everything worth emitting, in the order it will be written."""

    constants: list[tuple[str, int]] = field(default_factory=list)
    enums: list[Enum] = field(default_factory=list)
    records: list[Record] = field(default_factory=list)
    aliases: list[tuple[str, str]] = field(default_factory=list)
    functions: list[Function] = field(default_factory=list)
    statuses: list[tuple[str, int]] = field(default_factory=list)


# ── The pinned toolchain, so the output is reproducible ──────────────────────


def from_environment(name: str) -> Path:
    """Return the directory the named variable points at, or refuse to continue."""
    value = os.environ.get(name)
    if not value:
        raise GeneratorError(f"{name} is unset, run this inside `nix develop`")
    path = Path(value)
    if not path.is_dir():
        raise GeneratorError(f"{name} is {value!r}, which is not a directory")
    return path


def builtin_includes() -> Path:
    """Return the pinned clang's own header directory, the one holding stdint.h."""
    libclang = from_environment("LIBCLANG_PATH")
    for candidate in sorted(libclang.glob("clang/*/include")):
        if (candidate / "stdint.h").is_file():
            return candidate
    raise GeneratorError(f"no clang builtin headers under {libclang}")


def clang_args() -> list[str]:
    """Return the parse flags that keep this build off the system's headers."""
    return [
        "-std=c17",
        "-nostdinc",
        f"-I{builtin_includes()}",
        f"-I{from_environment('LIBC_INCLUDE')}",
        *(f"-I{d}" for d in INCLUDE_DIRS),
    ]


# ── Parsing ──────────────────────────────────────────────────────────────────


def not_none(value: T | None, what: str) -> T:
    """Return the value, or say which thing clang declined to report."""
    if value is None:
        raise GeneratorError(f"clang did not report {what}")
    return value


def parse(source: str, name: str = "fw_abi_gen.c") -> cindex.Cursor:
    """Return the root of the translation unit, refusing anything with errors."""
    # A header is not a translation unit and cannot be parsed alone, so the
    # source that includes them all is manufactured here and never written to
    # disk. Every declaration in every header then hangs off this one root,
    # which is why the callers filter on cursor.location.file.
    #
    # PARSE_DETAILED_PROCESSING_RECORD is what keeps macros in the AST. Clang
    # discards preprocessor definitions once it has used them.
    tu = cindex.Index.create().parse(
        name,
        args=clang_args(),
        unsaved_files=[(name, source)],
        options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD,
    )
    errors = [d for d in tu.diagnostics if d.severity >= cindex.Diagnostic.Error]
    if errors:
        raise GeneratorError("\n".join(str(d) for d in errors))
    return not_none(tu.cursor, f"a translation unit for {name}")


def includes() -> str:
    """Return the #include lines naming every header being read."""
    return "".join(f'#include "{Path(h).name}"\n' for h, _ in HEADERS)


# ── Macros, which clang reports as tokens and not values ─────────────────────


def is_function_like(cursor: cindex.Cursor) -> bool:
    """Whether the macro takes arguments, which no constant does."""
    tokens = list(cursor.get_tokens())
    return (
        len(tokens) > 1
        and tokens[1].spelling == "("
        and tokens[1].extent.start.offset == tokens[0].extent.end.offset
    )


def is_unnamed(cursor: cindex.Cursor) -> bool:
    """Whether the cursor names nothing clang can emit under."""
    return not cursor.spelling or "(unnamed" in cursor.spelling


def macro_names(root: cindex.Cursor, owned: dict[str, bool]) -> list[str]:
    """Return every object-like macro defined by the headers being read."""
    names: list[str] = []
    for cursor in root.get_children():
        if cursor.kind != CursorKind.MACRO_DEFINITION or not cursor.location.file:
            continue
        if Path(cursor.location.file.name).name not in owned:
            continue
        if len(list(cursor.get_tokens())) < 2 or is_function_like(cursor):
            continue
        names.append(cursor.spelling)
    return names


def macro_values(names: list[str]) -> list[tuple[str, int]]:
    """Return each macro's value, obtained by having clang evaluate it."""
    if not names:
        return []
    probes = "\n".join(f"enum {{ probe_{n} = ({n}) }};" for n in names)
    try:
        root = parse(includes() + probes + "\n", "fw_abi_gen_macros.c")
    except GeneratorError as exc:
        raise GeneratorError(f"a macro is not an integer constant:\n{exc}") from exc

    values: dict[str, int] = {}
    for cursor in root.walk_preorder():
        if cursor.kind == CursorKind.ENUM_CONSTANT_DECL and cursor.spelling.startswith(
            "probe_"
        ):
            values[cursor.spelling.removeprefix("probe_")] = cursor.enum_value
    missing = [n for n in names if n not in values]
    if missing:
        raise GeneratorError(f"macros did not evaluate: {', '.join(missing)}")
    return [(n, values[n]) for n in names]


# ── C types, one ctypes expression at a time ─────────────────────────────────


def ctype_of(type_: cindex.Type, records: set[str]) -> str:
    """Return the ctypes expression for a C type as it appears in a struct."""
    bare = type_.spelling.removeprefix("const ")
    if bare in STDINT:
        return STDINT[bare]

    if type_.kind in (TypeKind.TYPEDEF, TypeKind.ELABORATED):
        declared = type_.get_declaration().spelling
        if declared in records:
            return declared
        return ctype_of(type_.get_canonical(), records)

    if type_.kind == TypeKind.RECORD:
        name = type_.get_declaration().spelling
        if name not in records:
            raise GeneratorError(f"record {name!r} is not part of the emitted surface")
        return name

    if type_.kind == TypeKind.ENUM:
        return ctype_of(type_.get_declaration().enum_type, records)

    if type_.kind == TypeKind.CONSTANTARRAY:
        return f"{ctype_of(type_.element_type, records)} * {type_.element_count}"

    if type_.kind == TypeKind.POINTER:
        pointee = type_.get_pointee().get_canonical()
        if pointee.kind == TypeKind.VOID:
            return "ctypes.c_void_p"
        if pointee.kind in (TypeKind.CHAR_S, TypeKind.CHAR_U):
            return "ctypes.c_char_p"
        if pointee.kind == TypeKind.FUNCTIONPROTO:
            raise GeneratorError(f"{type_.spelling!r} is a function pointer")
        return f"ctypes.POINTER({ctype_of(type_.get_pointee(), records)})"

    if type_.kind in PRIMITIVES:
        return PRIMITIVES[type_.kind]

    raise GeneratorError(f"no ctypes equivalent for {type_.spelling!r} ({type_.kind})")


def argtype_of(type_: cindex.Type, records: set[str]) -> str:
    """Return the ctypes expression for a C type as it appears in a parameter."""
    if type_.kind == TypeKind.CONSTANTARRAY:
        return f"ctypes.POINTER({ctype_of(type_.element_type, records)})"
    return ctype_of(type_, records)


def record_of(cursor: cindex.Cursor, records: set[str]) -> Record:
    """Return the struct or union, with any flexible member set aside."""
    name = cursor.spelling
    fields: list[tuple[str, str]] = []
    flex = None
    members = list(cursor.type.get_fields())

    for index, member in enumerate(members):
        if member.type.kind != TypeKind.INCOMPLETEARRAY:
            fields.append((member.spelling, ctype_of(member.type, records)))
            continue
        if index != len(members) - 1:
            raise GeneratorError(f"{name}.{member.spelling} is not the last field")
        if COUNT_FIELD not in [f for f, _ in fields]:
            raise GeneratorError(
                f"{name}.{member.spelling} is flexible but {name} has no "
                f"{COUNT_FIELD!r} field to size it"
            )
        flex = (
            member.spelling,
            COUNT_FIELD,
            ctype_of(member.type.element_type, records),
        )

    return Record(
        name=name,
        kind="Union" if cursor.kind == CursorKind.UNION_DECL else "Structure",
        fields=fields,
        size=cursor.type.get_size(),
        flex=flex,
    )


# ── The pass itself ──────────────────────────────────────────────────────────


def collect() -> Abi:
    """Return everything the headers declare that the PC is entitled to see."""
    owned = {Path(h).name: emits_types for h, emits_types in HEADERS}
    root = parse(includes())
    abi = Abi()
    records: set[str] = set()

    abi.constants.extend(macro_values(macro_names(root, owned)))

    for cursor in root.get_children():
        if not cursor.location.file:
            continue
        header = Path(cursor.location.file.name).name
        if header not in owned:
            continue
        emits_types = owned[header]

        if cursor.kind == CursorKind.ENUM_DECL:
            members = [(c.spelling, c.enum_value) for c in cursor.get_children()]
            if is_unnamed(cursor):
                abi.constants.extend(members)
                if header in STATUS_HEADERS:
                    abi.statuses.extend(members)
            else:
                abi.enums.append(Enum(cursor.spelling, members))

        elif cursor.kind in (CursorKind.STRUCT_DECL, CursorKind.UNION_DECL):
            if emits_types and cursor.is_definition():
                abi.records.append(record_of(cursor, records))
                records.add(cursor.spelling)

        elif cursor.kind == CursorKind.TYPEDEF_DECL and emits_types:
            under = cursor.underlying_typedef_type
            canonical = under.get_canonical()
            if canonical.kind in (TypeKind.RECORD, TypeKind.ENUM):
                target = canonical.get_declaration().spelling
                if target != cursor.spelling and target in records:
                    abi.aliases.append((cursor.spelling, target))
                    records.add(cursor.spelling)
            else:
                abi.aliases.append((cursor.spelling, ctype_of(under, records)))

        elif cursor.kind == CursorKind.FUNCTION_DECL:
            if not emits_types or cursor.is_definition():
                continue
            abi.functions.append(
                Function(
                    name=cursor.spelling,
                    restype=(
                        None
                        if cursor.result_type.kind == TypeKind.VOID
                        else ctype_of(cursor.result_type, records)
                    ),
                    argtypes=[
                        argtype_of(
                            not_none(a, f"an argument of {cursor.spelling}").type,
                            records,
                        )
                        for a in cursor.get_arguments()
                    ],
                )
            )

    if not abi.statuses:
        raise GeneratorError("no status enumerators found")
    return abi


# ── Rendering the module ─────────────────────────────────────────────────────


def exception_name(status: str) -> str:
    """Return the class name a status enumerator is raised as."""
    return "Rpc" + "".join(
        p.capitalize() for p in status.removeprefix("RPC_").split("_")
    )


def render(abi: Abi) -> str:
    """Return the module source, ready for the formatter."""
    out: list[str] = []
    w = out.append

    w("# Generated by transport/tools/fw_abi_gen.py. Do not edit.")
    w("")
    w("import ctypes")
    w("import enum")
    w("import pathlib")
    w("import typing")
    w("")
    w('_lib = ctypes.CDLL(str(pathlib.Path(__file__).with_name("librpc.so")))')
    w("")
    for name, value in abi.constants:
        w(f"{name} = {value}")

    for item in abi.enums:
        w("")
        w("")
        w(f"class {item.name}(enum.IntEnum):")
        for member, value in item.members:
            w(f"    {member} = {value}")
        w("")
        for member, _ in item.members:
            w(f"{member} = {item.name}.{member}")

    for record in abi.records:
        w("")
        w("")
        w(f"class {record.name}(ctypes.{record.kind}):")
        w("    _fields_ = [")
        for member, ctype in record.fields:
            w(f'        ("{member}", {ctype}),')
        w("    ]")

    w("")
    w("")
    for name, target in abi.aliases:
        w(f"{name} = {target}")

    w("")
    w("SIZEOF = {")
    for record in abi.records:
        w(f'    "{record.name}": {record.size},')
    w("}")

    w("")
    w("")
    w("class Flex(typing.NamedTuple):")
    w("    field: str")
    w("    count_field: str")
    w("    elem: type")
    w("")
    w("")
    w("FLEX = {")
    for record in abi.records:
        if record.flex:
            member, count, elem = record.flex
            w(f'    {record.name}: Flex("{member}", "{count}", {elem}),')
    w("}")

    w("")
    w("")
    w("class RpcError(Exception):")
    w("    def __init__(self, status):")
    w("        self.status = status")
    w('        super().__init__(f"{rpc_strerror(status).decode()} ({status})")')

    raised = [(n, v) for n, v in abi.statuses if n not in STATUS_NOT_A_VALUE]
    for name, _ in raised:
        w("")
        w("")
        w(f"class {exception_name(name)}(RpcError):")
        w("    pass")

    w("")
    w("")
    w("STATUS_EXCEPTION = {")
    for name, _ in raised:
        w(f"    {name}: {exception_name(name)},")
    w("}")

    w("")
    w("")
    w("def raise_for_status(status):")
    w("    if status != RPC_OK:")
    w("        raise STATUS_EXCEPTION.get(status, RpcError)(status)")
    w("")

    for function in abi.functions:
        w("")
        w(f"{function.name} = _lib.{function.name}")
        w(f"{function.name}.restype = {function.restype}")
        w(f"{function.name}.argtypes = [{', '.join(function.argtypes)}]")

    return "\n".join(out) + "\n"


def formatted(text: str, filename: Path) -> str:
    """Return the text as ruff would commit it."""
    try:
        done = subprocess.run(
            ["ruff", "format", "--stdin-filename", str(filename), "-"],
            input=text,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise GeneratorError(
            "ruff is not on PATH, run this inside `nix develop`"
        ) from exc
    if done.returncode != 0:
        raise GeneratorError(f"ruff format rejected the output:\n{done.stderr.strip()}")
    return done.stdout


# ── Entry point ──────────────────────────────────────────────────────────────


def main() -> int:
    """Write the module, or report that the committed one no longer matches."""
    ap = argparse.ArgumentParser(
        description="Generate transport/fw_abi.py from the firmware headers"
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="fail if the committed fw_abi.py is not what the headers produce",
    )
    ap.add_argument("-o", "--output", type=Path, default=OUT)
    opts = ap.parse_args()

    try:
        text = formatted(render(collect()), opts.output)
    except GeneratorError as exc:
        print(f"fw_abi_gen: {exc}", file=sys.stderr)
        return 1

    if opts.check:
        if not opts.output.exists():
            print(f"fw_abi_gen: {opts.output} does not exist", file=sys.stderr)
            return 1
        if opts.output.read_text() != text:
            print(f"fw_abi_gen: {opts.output} is stale, regenerate it", file=sys.stderr)
            return 1
        return 0

    opts.output.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
