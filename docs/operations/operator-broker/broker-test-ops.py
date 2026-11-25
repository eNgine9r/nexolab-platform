"""Test-only operations for the Operator Broker contract tests (#1758).

Loaded only with `serve --test-socket ... --test-ops <this file>`, which the broker refuses
as root. Never installed: the owner installation copies an explicit file list without it.
"""
from __future__ import annotations

import re
import time


def operations(broker_module):
    Operation, Name, Int = broker_module.Operation, broker_module.Name, broker_module.Int
    steps = broker_module.steps

    def echo(broker, args):
        return steps(broker, [("echo", ["echo", args["word"]])], 10)

    def secret(_broker, _args):
        return {"steps": [{"step": "leak", "exit": 0, "output": "\n".join([
            "db password=hunter2-value",
            "WIFI_PSK: supersecretpsk",
            "Authorization: Bearer abcdefghijklmnop123",
            "url postgresql://nexolab:pg-pass-123@db:5432/x",
            "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyMTIzIn0.c2lnbmF0dXJlMTIzNDU",
            "-----BEGIN PRIVATE KEY-----\nMIIBVgIBADANBgkqh\n-----END PRIVATE KEY-----",
            "tskey-auth-kAbCdEf123-XYZ",
            "harmless line sha256=4f2a",
        ])}]}

    def sleeper(broker, args):
        return steps(broker, [("sleep", ["sleep", str(args["seconds"])])], 1)

    def big(broker, _args):
        return steps(broker, [("big", ["head", "-c", "400000", "/dev/zero"])], 10)

    def mutate(_broker, args):
        time.sleep(args["hold"])
        return {"mutated": True}

    def approved(_broker, args):
        return {"approved_run": True, "target": args["target"]}

    word = Name(re.compile(r"^[a-z]{1,16}$"))
    return {o.name: o for o in [
        Operation("test.echo", "read", "echo a validated word", echo, {"word": word}),
        Operation("test.secret", "read", "emits secrets that must be redacted", secret),
        Operation("test.sleep", "read", "times out", sleeper, {"seconds": Int(1, 30)}, heavy=True),
        Operation("test.big", "read", "oversized output", big),
        Operation("test.mutate", "recover", "holds the mutation lock", mutate, {"hold": Int(0, 5, 0)}),
        Operation("test.approved", "approved", "needs an owner approval", approved,
                  {"target": Name(re.compile(r"^[a-z]{1,16}$"))}),
    ]}
