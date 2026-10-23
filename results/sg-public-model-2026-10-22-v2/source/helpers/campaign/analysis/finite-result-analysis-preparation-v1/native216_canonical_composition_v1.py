"""Inert, dependency-injected native216 canonical transport composition.

Caller injects independently pinned/qualified CanonicalJSONResolver class,
storage.regular_reader, exact approved lookup entries, InventoryProxy class,
native frontier module, unchanged inventory/audit objects, and the create-only
native216_orchestrator_v2_canonical module. No dependency imports, discovery,
monkeypatching, restore/retire action, temporary raw file, or model at import.

This wiring is not an acceptance/release: the caller still owns input/source
qualification, approved archive ancestry, resource admission, and the one lock.
The resolver's declared archive membership is not a fabricated exists() result.
"""

DOCUMENT_LIMIT_BYTES = 8_388_608


def need(ok, message):
    if not ok:
        raise ValueError(message)


class Native216CanonicalComposition:
    def __init__(self, *, base_io, approved_entries, resolver_class,
                 regular_reader, inventory_proxy_class, frontier_module,
                 inv, audit, orchestration):
        self.base_io = base_io
        self.io = resolver_class(base_io, approved_entries, regular_reader,
                                 DOCUMENT_LIMIT_BYTES)
        need(self.io.bindings is base_io.bindings,
             "canonical resolver must retain the exact base binding map")
        need(callable(getattr(self.io, "is_approved_archive_path", None)),
             "canonical resolver must expose explicit approved archive membership")
        self.inventory = inventory_proxy_class(inv, self.io, frontier_module)
        need(self.inventory.io is self.io and self.inventory.inv is inv,
             "inventory proxy must retain the injected inventory and canonical IO")
        self.audit = audit
        self.orchestration = orchestration

    def run_native_window(self, binding, out):
        need(self.io.bindings is self.base_io.bindings,
             "canonical IO binding map changed before orchestration")
        return self.orchestration.run_native_window(
            binding, self.io, out, self.inventory, self.audit)


def run_native_window(binding, base_io, out, inv, audit=None, *,
                      approved_entries, resolver_class, regular_reader,
                      inventory_proxy_class, frontier_module, orchestration):
    """Convenience entry point with every transport dependency explicit."""
    composition = Native216CanonicalComposition(
        base_io=base_io, approved_entries=approved_entries,
        resolver_class=resolver_class, regular_reader=regular_reader,
        inventory_proxy_class=inventory_proxy_class, frontier_module=frontier_module,
        inv=inv, audit=audit, orchestration=orchestration)
    return composition.run_native_window(binding, out)
