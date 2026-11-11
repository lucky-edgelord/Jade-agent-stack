"""Portable playbooks (*.playbook.yaml): YAML automation that compiles to each target's existing primitives (Base
tools, Vault's HTTP API, a Kit page, local commands). They do not replace Vault playbooks, flows or Jade Lisp.

    pb = jade.playbook.load("examples/provision-booking-app.playbook.yaml")
    pb.check(harness)          # schema, expressions, targets, tools and their arguments
    pb.plan()                  # every call it would make; makes none
    for ev in pb.run(harness): # step events; resumable
        print(ev)
"""

from .engine import Playbook, approve, approved, discover, load, revoke, runs, SCHEMA

__all__ = ["Playbook", "load", "discover", "approve", "revoke", "approved", "runs", "SCHEMA"]
