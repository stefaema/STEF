import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

import clang.cindex as cindex
from clang.cindex import CursorKind, TypeKind

T = TypeVar("T")

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = Path(__file__).resolve().parents[1]
OUT = PACKAGE / "fw_api.py"

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


class GeneratorError(Exception):
    pass


@dataclass
class Record:
    name: str
    kind: str
    fields: list[tuple[str, str]]
    size: int
    flex: tuple[str, str, str] | None = None


@dataclass
class Enum:
    name: str
    members: list[tuple[str, int]]


@dataclass
class Function:
    name: str
    restype: str | None
    argtypes: list[str]


@dataclass
class Api:
    constants: list[tuple[str, int]] = field(default_factory=list)
    enums: list[Enum] = field(default_factory=list)
    records: list[Record] = field(default_factory=list)
    aliases: list[tuple[str, str]] = field(default_factory=list)
    functions: list[Function] = field(default_factory=list)
    statuses: list[tuple[str, int]] = field(default_factory=list)


def from_environment(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        raise GeneratorError(f"{name} is unset, run this inside `nix develop`")
    path = Path(value)
    if not path.is_dir():
        raise GeneratorError(f"{name} is {value!r}, which is not a directory")
    return path


def builtin_includes() -> Path:
    libclang = from_environment("LIBCLANG_PATH")
    for candidate in sorted(libclang.glob("clang/*/include")):
        if (candidate / "stdint.h").is_file():
            return candidate
    raise GeneratorError(f"no clang builtin headers under {libclang}")


def clang_args() -> list[str]:
    return [
        "-std=c17",
        "-nostdinc",
        f"-I{builtin_includes()}",
        f"-I{from_environment('LIBC_INCLUDE')}",
        *(f"-I{d}" for d in INCLUDE_DIRS),
    ]


def not_none(value: T | None, what: str) -> T:
    if value is None:
        raise GeneratorError(f"clang did not report {what}")
    return value


def parse(source: str, name: str = "fw_api_gen.c") -> cindex.Cursor:
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
    return "".join(f'#include "{Path(h).name}"\n' for h, _ in HEADERS)


def is_function_like(cursor: cindex.Cursor) -> bool:
    tokens = list(cursor.get_tokens())
    return (
        len(tokens) > 1
        and tokens[1].spelling == "("
        and tokens[1].extent.start.offset == tokens[0].extent.end.offset
    )


def is_unnamed(cursor: cindex.Cursor) -> bool:
    return not cursor.spelling or "(unnamed" in cursor.spelling


def macro_names(root: cindex.Cursor, owned: dict[str, bool]) -> list[str]:
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
    if not names:
        return []
    probes = "\n".join(f"enum {{ probe_{n} = ({n}) }};" for n in names)
    try:
        root = parse(includes() + probes + "\n", "fw_api_gen_macros.c")
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


def ctype_of(type_: cindex.Type, records: set[str]) -> str:
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
    if type_.kind == TypeKind.CONSTANTARRAY:
        return f"ctypes.POINTER({ctype_of(type_.element_type, records)})"
    return ctype_of(type_, records)


def record_of(cursor: cindex.Cursor, records: set[str]) -> Record:
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


def collect() -> Api:
    owned = {Path(h).name: emits_types for h, emits_types in HEADERS}
    root = parse(includes())
    api = Api()
    records: set[str] = set()

    api.constants.extend(macro_values(macro_names(root, owned)))

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
                api.constants.extend(members)
                if header in STATUS_HEADERS:
                    api.statuses.extend(members)
            else:
                api.enums.append(Enum(cursor.spelling, members))

        elif cursor.kind in (CursorKind.STRUCT_DECL, CursorKind.UNION_DECL):
            if emits_types and cursor.is_definition():
                api.records.append(record_of(cursor, records))
                records.add(cursor.spelling)

        elif cursor.kind == CursorKind.TYPEDEF_DECL and emits_types:
            under = cursor.underlying_typedef_type
            canonical = under.get_canonical()
            if canonical.kind in (TypeKind.RECORD, TypeKind.ENUM):
                target = canonical.get_declaration().spelling
                if target != cursor.spelling and target in records:
                    api.aliases.append((cursor.spelling, target))
                    records.add(cursor.spelling)
            else:
                api.aliases.append((cursor.spelling, ctype_of(under, records)))

        elif cursor.kind == CursorKind.FUNCTION_DECL:
            if not emits_types or cursor.is_definition():
                continue
            api.functions.append(
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

    if not api.statuses:
        raise GeneratorError("no status enumerators found")
    return api


def exception_name(status: str) -> str:
    return "Rpc" + "".join(
        p.capitalize() for p in status.removeprefix("RPC_").split("_")
    )


def render(api: Api) -> str:
    out: list[str] = []
    w = out.append

    w("# Generated by transport/tools/fw_api_gen.py. Do not edit.")
    w("")
    w("import ctypes")
    w("import enum")
    w("import pathlib")
    w("import typing")
    w("")
    w('_lib = ctypes.CDLL(str(pathlib.Path(__file__).with_name("librpc.so")))')
    w("")
    for name, value in api.constants:
        w(f"{name} = {value}")

    for item in api.enums:
        w("")
        w("")
        w(f"class {item.name}(enum.IntEnum):")
        for member, value in item.members:
            w(f"    {member} = {value}")
        w("")
        for member, _ in item.members:
            w(f"{member} = {item.name}.{member}")

    for record in api.records:
        w("")
        w("")
        w(f"class {record.name}(ctypes.{record.kind}):")
        w("    _fields_ = [")
        for member, ctype in record.fields:
            w(f'        ("{member}", {ctype}),')
        w("    ]")

    w("")
    w("")
    for name, target in api.aliases:
        w(f"{name} = {target}")

    w("")
    w("SIZEOF = {")
    for record in api.records:
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
    for record in api.records:
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

    raised = [(n, v) for n, v in api.statuses if n not in STATUS_NOT_A_VALUE]
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

    for function in api.functions:
        w("")
        w(f"{function.name} = _lib.{function.name}")
        w(f"{function.name}.restype = {function.restype}")
        w(f"{function.name}.argtypes = [{', '.join(function.argtypes)}]")

    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate transport/fw_api.py from the firmware headers"
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="fail if the committed fw_api.py is not what the headers produce",
    )
    ap.add_argument("-o", "--output", type=Path, default=OUT)
    opts = ap.parse_args()

    try:
        text = render(collect())
    except GeneratorError as exc:
        print(f"fw_api_gen: {exc}", file=sys.stderr)
        return 1

    if opts.check:
        if not opts.output.exists():
            print(f"fw_api_gen: {opts.output} does not exist", file=sys.stderr)
            return 1
        if opts.output.read_text() != text:
            print(f"fw_api_gen: {opts.output} is stale, regenerate it", file=sys.stderr)
            return 1
        return 0

    opts.output.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
