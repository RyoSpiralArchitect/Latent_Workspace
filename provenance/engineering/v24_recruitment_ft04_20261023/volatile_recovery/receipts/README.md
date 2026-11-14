# Metadata only

These receipts describe the private, same-host Furnace volatile-data recovery.
Raw temporary files, feature tensors, opaque shared-memory segments, and terminal
captures remain in the owner-only SSD capsule on Furnace. Do not publish those
payloads, execute recovered scripts, or restore runtime units/locks automatically.
The capsule is a data quarantine, not a resumable process or a complete interactive
session checkpoint. Its source payloads were not deleted or changed.
