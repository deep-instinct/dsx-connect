from __future__ import annotations

from collections.abc import Mapping

from dsx_transfer.models import TransferAction


WINDOWS_EXECUTABLE_FILE_TYPES = {
    "PEFileType",
    "PE32FileType",
    "PE64FileType",
}

LINUX_EXECUTABLE_FILE_TYPES = {
    "ELF32FileType",
    "ELF64FileType",
}

MACOS_EXECUTABLE_FILE_TYPES = {
    "MachoFATFileType",
    "Macho32FileType",
    "Macho64FileType",
}

FILE_TYPE_GROUPS: dict[str, set[str]] = {
    "windows_executables": WINDOWS_EXECUTABLE_FILE_TYPES,
    "linux_executables": LINUX_EXECUTABLE_FILE_TYPES,
    "macos_executables": MACOS_EXECUTABLE_FILE_TYPES,
    "executables": WINDOWS_EXECUTABLE_FILE_TYPES | LINUX_EXECUTABLE_FILE_TYPES | MACOS_EXECUTABLE_FILE_TYPES,
}


def expand_file_type_actions(actions: Mapping[str, TransferAction]) -> dict[str, TransferAction]:
    expanded: dict[str, TransferAction] = {}
    for file_type_or_group, action in actions.items():
        if file_type_or_group in FILE_TYPE_GROUPS:
            for file_type in FILE_TYPE_GROUPS[file_type_or_group]:
                expanded[file_type] = action
            continue
        expanded[file_type_or_group] = action
    return expanded
