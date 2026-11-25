"""Emulate systemd RestrictAddressFamilies= for one child process (tests and diagnostics, #1756).

systemd implements RestrictAddressFamilies= as a seccomp filter: socket(2) with a
family outside the allow-list fails with EAFNOSUPPORT (errno 97). This helper
installs the same filter (unprivileged, after PR_SET_NO_NEW_PRIVS) and execs the
given command, so the real gateway can be exercised under the unit's sandbox in CI.

    python3 sandbox-restrict-address-families.py AF_INET,AF_INET6,AF_UNIX -- node gateway.mjs
"""

from __future__ import annotations

import ctypes
import os
import platform
import struct
import sys

FAMILIES = {"AF_UNIX": 1, "AF_INET": 2, "AF_INET6": 10, "AF_NETLINK": 16, "AF_PACKET": 17}
SOCKET_NR = {"x86_64": 41, "aarch64": 198}
AUDIT_ARCH = {"x86_64": 0xC000003E, "aarch64": 0xC00000B7}
EAFNOSUPPORT = 97

BPF_LD_W_ABS, BPF_JEQ_K, BPF_RET_K = 0x20, 0x15, 0x06
SECCOMP_RET_ALLOW, SECCOMP_RET_ERRNO = 0x7FFF0000, 0x00050000
PR_SET_NO_NEW_PRIVS, PR_SET_SECCOMP, SECCOMP_MODE_FILTER = 38, 22, 2


def supported() -> bool:
    return sys.platform == "linux" and platform.machine() in SOCKET_NR


def _filter(allowed: list[int]) -> tuple[bytes, int]:
    machine = platform.machine()
    ins = [
        (BPF_LD_W_ABS, 0, 0, 4),  # seccomp_data.arch
        (BPF_JEQ_K, 1, 0, AUDIT_ARCH[machine]),
        (BPF_RET_K, 0, 0, SECCOMP_RET_ALLOW),
        (BPF_LD_W_ABS, 0, 0, 0),  # seccomp_data.nr
        (BPF_JEQ_K, 1, 0, SOCKET_NR[machine]),
        (BPF_RET_K, 0, 0, SECCOMP_RET_ALLOW),
        (BPF_LD_W_ABS, 0, 0, 16),  # args[0] low 32 bits (little endian): the address family
    ]
    for index, family in enumerate(allowed):
        remaining = len(allowed) - index - 1
        ins.append((BPF_JEQ_K, remaining + 1, 0, family))  # match -> ALLOW (after the deny)
    ins.append((BPF_RET_K, 0, 0, SECCOMP_RET_ERRNO | EAFNOSUPPORT))
    ins.append((BPF_RET_K, 0, 0, SECCOMP_RET_ALLOW))
    return b"".join(struct.pack("HBBI", code, jt, jf, k) for code, jt, jf, k in ins), len(ins)


def main(argv: list[str]) -> int:
    if not supported():
        print("unsupported platform", file=sys.stderr)
        return 77
    families = [FAMILIES[name] for name in argv[1].split(",") if name]
    command = argv[argv.index("--") + 1 :]
    program, count = _filter(families)
    buffer = ctypes.create_string_buffer(program)

    class SockFprog(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.c_void_p)]

    prog = SockFprog(count, ctypes.addressof(buffer))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "PR_SET_NO_NEW_PRIVS")
    if libc.prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, ctypes.byref(prog), 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "PR_SET_SECCOMP")
    os.execvp(command[0], command)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
