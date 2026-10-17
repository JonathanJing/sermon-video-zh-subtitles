"""Shared storage infrastructure: files, locks, snapshots and remote objects.

Stages reach it through their ports. It imports no stage layer. Modules arrive
one batch at a time (docs/design/infrastructure-injection.zh.md); the Hosting
adapter came first, with L4 D3 (docs/design/l4-delivery-layer-injection.zh.md);
infrastructure I2 added the path constraint, atomic files, work locks and the public snapshot.
"""
