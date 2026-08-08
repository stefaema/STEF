"""Turns the firmware headers into abi.py, the PC's view of the same ABI."""

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

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parents[1]
OUT = PACKAGE / "abi.py"

INCLUDE_DIRS = [
    ROOT / "portable" / "rpc" / "include",
    ROOT / "shared" / "fw_api" / "include",
    ROOT / "portable" / "tmc2209" / "include",
]

TYPES_AND_FUNCTIONS = True
NAMES_ONLY = False

HEADERS = [
    ("portable/rpc/include/rpc_proto.h", TYPES_AND_FUNCTIONS),
    ("portable/rpc/include/rpc_frame.h", TYPES_AND_FUNCTIONS),
    ("portable/rpc/include/cobs.h", TYPES_AND_FUNCTIONS),
    ("portable/rpc/include/crc16.h", TYPES_AND_FUNCTIONS),
    ("shared/fw_api/include/fw_api.h", TYPES_AND_FUNCTIONS),
    ("portable/tmc2209/include/tmc2209_err.h", TYPES_AND_FUNCTIONS),
    ("portable/tmc2209/include/tmc2209_frame.h", TYPES_AND_FUNCTIONS),
    ("portable/tmc2209/include/tmc2209_reg.h", TYPES_AND_FUNCTIONS),
    ("portable/tmc2209/include/tmc2209_lines.h", NAMES_ONLY),
    ("portable/tmc2209/include/tmc2209_stepgen.h", NAMES_ONLY),
]

STATUS_HEADERS = {"rpc_proto.h", "fw_api.h"}

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

# What a semantic typedef can be an alias for: any width the wire uses. A
# typedef over an enum or a record is a different thing and is not one of these.
STDINT_KINDS = {
    TypeKind.CHAR_S,
    TypeKind.CHAR_U,
    TypeKind.SCHAR,
    TypeKind.UCHAR,
    TypeKind.SHORT,
    TypeKind.USHORT,
    TypeKind.INT,
    TypeKind.UINT,
    TypeKind.LONG,
    TypeKind.ULONG,
    TypeKind.LONGLONG,
    TypeKind.ULONGLONG,
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


# ── How this fails ───────────────────────────────────────────────────────────


class GeneratorError(Exception):
    """Anything that makes the headers unreadable or the output untrustworthy."""


def not_none(value: T | None, what: str) -> T:
    """Return the value, or say which thing clang declined to report."""
    if value is None:
        raise GeneratorError(f"clang did not report {what}")
    return value


# ── What one pass collects ───────────────────────────────────────────────────


@dataclass
class Record:
    """One struct or union, its fields already rendered as ctypes source."""

    name: str
    kind: str
    fields: list[tuple[str, str]]
    size: int
    flex: tuple[str, str, str] | None = None
    semantic: dict[str, str] = field(default_factory=dict)
    doc: str | None = None
    field_docs: dict[str, str] = field(default_factory=dict)


@dataclass
class Enum:
    """One named C enum and the value of each enumerator."""

    name: str
    members: list[tuple[str, int]]
    doc: str | None = None
    member_docs: dict[str, str] = field(default_factory=dict)


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
    semantic_typedefs: list[str] = field(default_factory=list)


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


def parse(source: str, name: str = "abi_gen.c") -> cindex.Cursor:
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


def macro_names(root: cindex.Cursor, owned: dict[str, bool]) -> dict[str, str]:
    """Return every object-like macro the headers define, against the header naming it."""
    names: dict[str, str] = {}
    for cursor in root.get_children():
        if cursor.kind != CursorKind.MACRO_DEFINITION or not cursor.location.file:
            continue
        header = Path(cursor.location.file.name).name
        if header not in owned:
            continue
        if len(list(cursor.get_tokens())) < 2 or is_function_like(cursor):
            continue
        names[cursor.spelling] = header
    return names


def macro_values(names: list[str]) -> list[tuple[str, int]]:
    """Return each macro's value, obtained by having clang evaluate it."""
    if not names:
        return []
    probes = "\n".join(f"enum {{ probe_{n} = ({n}) }};" for n in names)
    try:
        root = parse(includes() + probes + "\n", "abi_gen_macros.c")
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


# ── Comments, so prose is authored once and in C ─────────────────────────────

BRIEF = "@brief "


def clean_comment(raw: str | None) -> str | None:
    """Return the comment's text in PEP 257 shape, or None if there was none."""
    if not raw:
        return None

    body = raw.strip()
    for opener in ("/**<", "/**", "/*!", "/*"):
        if body.startswith(opener):
            body = body[len(opener) :]
            break
    body = body.removesuffix("*/")

    lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("*") and not stripped.startswith("*/"):
            stripped = stripped[1:].lstrip()
        lines.append(stripped)

    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    if not lines:
        return None

    if lines[0].startswith(BRIEF):
        lines[0] = lines[0][len(BRIEF) :]
    # PEP 257: a summary line, then a blank, then whatever else was said.
    if len(lines) > 1 and lines[1]:
        lines.insert(1, "")
    return "\n".join(lines).strip() or None


def docstring(text: str, indent: str) -> list[str]:
    """Return the lines of a triple-quoted docstring holding the text verbatim."""
    safe = text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    lines = safe.split("\n")
    if len(lines) == 1:
        return [f'{indent}"""{lines[0]}"""']
    return [
        f'{indent}"""{lines[0]}',
        *(f"{indent}{ln}".rstrip() for ln in lines[1:]),
        f'{indent}"""',
    ]


# ── C types, one ctypes expression at a time ─────────────────────────────────

COUNT_FIELD = "count"


def ctype_of(type_: cindex.Type, records: set[str]) -> str:
    """Return the ctypes expression for a C type as it appears in a struct."""
    bare = type_.spelling.removeprefix("const ")
    if bare in STDINT:
        return STDINT[bare]

    if type_.kind in (TypeKind.TYPEDEF, TypeKind.ELABORATED):
        declared = type_.get_declaration().spelling
        if declared in records:
            return declared
        # One typedef at a time, so a semantic typedef over uint8_t lands on the
        # stdint spelling and not on the canonical `unsigned char`.
        under = type_.get_declaration().underlying_typedef_type
        if under.kind != TypeKind.INVALID:
            return ctype_of(under, records)
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


def written_type(type_: cindex.Type, records: set[str]) -> str | None:
    """Return the semantic typedef a field was declared with, or None for a bare width."""
    if type_.kind not in (TypeKind.TYPEDEF, TypeKind.ELABORATED):
        return None
    spelling = type_.spelling.removeprefix("const ")
    if spelling in STDINT or spelling in records:
        return None
    return spelling


def record_of(cursor: cindex.Cursor, records: set[str]) -> Record:
    """Return the struct or union, with any flexible member set aside."""
    name = cursor.spelling
    fields: list[tuple[str, str]] = []
    semantic: dict[str, str] = {}
    field_docs: dict[str, str] = {}
    flex = None
    members = list(cursor.type.get_fields())

    for index, member in enumerate(members):
        written = written_type(member.type, records)
        if written is not None:
            semantic[member.spelling] = written
        note = clean_comment(member.raw_comment)
        if note is not None:
            field_docs[member.spelling] = note

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
        semantic=semantic,
        doc=clean_comment(cursor.raw_comment),
        field_docs=field_docs,
    )


# ── The pass itself ──────────────────────────────────────────────────────────


def in_header_order(tagged: list[tuple[int, T]]) -> list[T]:
    """Return the items grouped by the header that declared them, HEADERS' order.

    AST order follows the include graph, so an added include would otherwise
    relayout the whole file.
    """
    return [item for _, item in sorted(tagged, key=lambda pair: pair[0])]


def collect() -> Abi:
    """Return everything the headers declare that the PC is entitled to see."""
    owned = {Path(h).name: emits_types for h, emits_types in HEADERS}
    rank = {Path(h).name: index for index, (h, _) in enumerate(HEADERS)}
    root = parse(includes())
    abi = Abi()
    records: set[str] = set()

    macro_headers = macro_names(root, owned)
    macros = [
        (rank[macro_headers[name]], (name, value))
        for name, value in macro_values(list(macro_headers))
    ]

    enum_constants: list[tuple[int, tuple[str, int]]] = []
    enums: list[tuple[int, Enum]] = []
    structs: list[tuple[int, Record]] = []
    aliases: list[tuple[int, tuple[str, str]]] = []
    functions: list[tuple[int, Function]] = []
    statuses: list[tuple[int, tuple[str, int]]] = []

    for cursor in root.get_children():
        if not cursor.location.file:
            continue
        header = Path(cursor.location.file.name).name
        if header not in owned:
            continue
        emits_types = owned[header]
        order = rank[header]

        if cursor.kind == CursorKind.ENUM_DECL:
            members = [(c.spelling, c.enum_value) for c in cursor.get_children()]
            if is_unnamed(cursor):
                enum_constants += [(order, m) for m in members]
                if header in STATUS_HEADERS:
                    statuses += [(order, m) for m in members]
            else:
                enums.append(
                    (
                        order,
                        Enum(
                            name=cursor.spelling,
                            members=members,
                            doc=clean_comment(cursor.raw_comment),
                            member_docs={
                                c.spelling: note
                                for c in cursor.get_children()
                                if (note := clean_comment(c.raw_comment)) is not None
                            },
                        ),
                    )
                )

        elif cursor.kind in (CursorKind.STRUCT_DECL, CursorKind.UNION_DECL):
            if emits_types and cursor.is_definition():
                structs.append((order, record_of(cursor, records)))
                records.add(cursor.spelling)

        elif cursor.kind == CursorKind.TYPEDEF_DECL:
            under = cursor.underlying_typedef_type
            canonical = under.get_canonical()
            if canonical.kind in STDINT_KINDS and cursor.spelling not in STDINT:
                abi.semantic_typedefs.append(cursor.spelling)
            if not emits_types:
                continue
            if canonical.kind in (TypeKind.RECORD, TypeKind.ENUM):
                target = canonical.get_declaration().spelling
                if target != cursor.spelling and target in records:
                    aliases.append((order, (cursor.spelling, target)))
                    records.add(cursor.spelling)
            else:
                aliases.append((order, (cursor.spelling, ctype_of(under, records))))

        elif cursor.kind == CursorKind.FUNCTION_DECL:
            if not emits_types or cursor.is_definition():
                continue
            functions.append(
                (
                    order,
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
                    ),
                )
            )

    abi.constants = in_header_order(macros) + in_header_order(enum_constants)
    abi.enums = in_header_order(enums)
    abi.records = in_header_order(structs)
    abi.aliases = in_header_order(aliases)
    abi.functions = in_header_order(functions)
    abi.statuses = in_header_order(statuses)

    if not abi.statuses:
        raise GeneratorError("no status enumerators found")
    return abi


# ── The Python enums the C enums imply ───────────────────────────────────────

ID_SUFFIX = "_id_t"
MASK_SUFFIX = "_mask_t"
TERMINATOR = "_COUNT"


@dataclass
class PyEnum:
    """One generated enum class, and every C spelling that resolves to it."""

    name: str
    base: str
    members: list[tuple[str, str, int]]
    doc: str | None
    flat: bool
    spellings: list[str] = field(default_factory=list)


def class_name_of(c_name: str) -> str:
    """Return the CamelCase class name a C type name is emitted under."""
    return "".join(part.capitalize() for part in c_name.removesuffix("_t").split("_"))


def short_names(members: list[tuple[str, int]]) -> dict[str, str]:
    """Return each member's name with the prefix they all share dropped, where that works.

    The alias lets a call site write `Tmc2209Reg.GCONF`. Where dropping the
    prefix would leave a digit or nothing, the C name is the only name.
    """
    names = [name for name, _ in members]
    if len(names) < 2:
        return {}
    prefix = os.path.commonprefix(names)
    prefix = prefix[: prefix.rfind("_") + 1]
    if not prefix:
        return {}
    short = {name: name[len(prefix) :] for name in names}
    if any(not s.isidentifier() or s[0].isdigit() for s in short.values()):
        return {}
    return {name: s for name, s in short.items() if s != name}


def is_bit_valued(members: list[tuple[str, int]]) -> bool:
    """Whether every enumerator is one distinct bit, so the enum is already a flag set."""
    values = [value for _, value in members]
    return bool(values) and all(v > 0 and v & (v - 1) == 0 for v in values)


def py_enums(abi: Abi) -> list[PyEnum]:
    """Return the enum classes to emit, with the C spellings each one answers to.

    A `*_mask_t` over single-bit enumerators is a flag set. Over an index enum it
    gets a class of its own at `1 << index`, since the macro saying so does not
    survive preprocessing. Everything else is an ordinary enumeration.
    """

    masked = {
        name.removesuffix(MASK_SUFFIX) + "_t": name
        for name in abi.semantic_typedefs
        if name.endswith(MASK_SUFFIX)
    }
    named = {
        name.removesuffix(ID_SUFFIX) + "_t": name
        for name in abi.semantic_typedefs
        if name.endswith(ID_SUFFIX)
    }

    out: list[PyEnum] = []
    for item in abi.enums:
        short = short_names(item.members)
        mask = masked.get(item.name)
        flags = mask is not None and is_bit_valued(item.members)

        spellings = [item.name]
        if item.name in named:
            spellings.append(named[item.name])
        if flags:
            spellings.append(masked[item.name])

        out.append(
            PyEnum(
                name=class_name_of(item.name),
                base="IntFlag" if flags else "IntEnum",
                members=[(name, short.get(name, ""), v) for name, v in item.members],
                doc=item.doc,
                flat=True,
                spellings=spellings,
            )
        )

        if mask is None or flags:
            continue
        out.append(
            PyEnum(
                name=class_name_of(mask),
                base="IntFlag",
                members=[
                    (name, short.get(name, ""), 1 << value)
                    for name, value in item.members
                    if not name.endswith(TERMINATOR)
                ],
                doc=f"One bit per {item.name}, as {mask} carries them.",
                flat=False,
                spellings=[mask],
            )
        )

    return out


# ── Rendering the module ─────────────────────────────────────────────────────

STATUS_NOT_A_VALUE = {"RPC_OK", "RPC_STATUS_LAST"}


def exception_name(status: str) -> str:
    """Return the class name a status enumerator is raised as."""
    return "Rpc" + "".join(
        p.capitalize() for p in status.removeprefix("RPC_").split("_")
    )


def render(abi: Abi) -> str:
    """Return the module source, ready for the formatter."""
    out: list[str] = []
    w = out.append

    w("# Generated by shared/fw_api/tools/abi_gen.py. Do not edit.")
    w("")
    w("import ctypes")
    w("import enum")
    w("import pathlib")
    w("import typing")
    w("")
    w(
        '_lib = ctypes.CDLL(str(pathlib.Path(__file__).parent / "build" / "libfw_api.so"))'
    )
    w("")
    for name, value in abi.constants:
        w(f"{name} = {value}")

    classes = py_enums(abi)
    for item in classes:
        w("")
        w("")
        w(f"class {item.name}(enum.{item.base}):")
        if item.doc:
            out.extend(docstring(item.doc, "    "))
            w("")
        for member, short, value in item.members:
            w(f"    {member} = {value}")
            if short:
                w(f"    {short} = {value}")
        if item.flat:
            w("")
            w(f"{item.spellings[0]} = {item.name}")
            for member, _, _ in item.members:
                w(f"{member} = {item.name}.{member}")

    for record in abi.records:
        w("")
        w("")
        w(f"class {record.name}(ctypes.{record.kind}):")
        if record.doc:
            out.extend(docstring(record.doc, "    "))
            w("")
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
    w("SEMANTIC = {")
    for record in abi.records:
        if not record.semantic:
            continue
        written = ", ".join(f'"{f}": "{t}"' for f, t in record.semantic.items())
        w(f"    {record.name}: {{{written}}},")
    w("}")

    w("")
    w("PY_ENUM = {")
    for item in classes:
        for spelling in item.spellings:
            w(f'    "{spelling}": {item.name},')
    w("}")

    w("")
    w("DOC = {")
    for item in abi.enums:
        for member, note in item.member_docs.items():
            w(f'    "{item.name}.{member}": {note!r},')
    for record in abi.records:
        for member, note in record.field_docs.items():
            w(f'    "{record.name}.{member}": {note!r},')
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
        description="Generate shared/fw_api/abi.py from the firmware headers"
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="fail if the committed abi.py is not what the headers produce",
    )
    ap.add_argument("-o", "--output", type=Path, default=OUT)
    opts = ap.parse_args()

    try:
        text = formatted(render(collect()), opts.output)
    except GeneratorError as exc:
        print(f"abi_gen: {exc}", file=sys.stderr)
        return 1

    if opts.check:
        if not opts.output.exists():
            print(f"abi_gen: {opts.output} does not exist", file=sys.stderr)
            return 1
        if opts.output.read_text() != text:
            print(f"abi_gen: {opts.output} is stale, regenerate it", file=sys.stderr)
            return 1
        return 0

    opts.output.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
