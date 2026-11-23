import pytest
from xjp60d import XJP60DReader
from xjp60d_sections import connected_count, read_section, section_equipment_id


def test_section_two_reads_next_unit_not_next_register():
    class Client:
        def __init__(self): self.calls = []
        def read_holding_register(self, unit, address):
            self.calls.append((unit, address))
            if address not in (256, 257): raise AssertionError("unsupported register")
            return 219 if address == 256 else 0x1100
    client = Client()
    reading = read_section(XJP60DReader(client), 7, 2)
    assert client.calls == [(8, 256), (8, 257)]
    assert reading.quality == "valid" and reading.value == pytest.approx(21.9)


def test_section_identity_is_distinct_from_old_k_and_other_bus():
    assert section_equipment_id("bus-a", 1) != section_equipment_id("bus-b", 1)
    assert section_equipment_id("bus-a", 1) != "K1"


def test_connected_count_is_strict_and_bounds_checked():
    assert connected_count("dixell-xjp60d-sections-v1-2") == 2
    assert connected_count("dixell-xjp60d-fc03-v1") is None
    for bad in ["dixell-xjp60d-sections-v1-0", "dixell-xjp60d-sections-v1-7"]:
        with pytest.raises(ValueError): connected_count(bad)


def test_section_group_registry_range_and_reserved_inputs():
    from test_acquisition_registry import settings
    from acquisition_registry import AcquisitionRegistry, build_initial_document
    registry = AcquisitionRegistry(build_initial_document(settings(), discovery_units=(), legacy_active_points=()))
    doc, _ = registry.with_xjp60d_enrollment([1], profile_version="dixell-xjp60d-sections-v1-2")
    device = next(d for d in doc.devices if d.unit_id == 1)
    targets = [t for t in doc.targets if t.device_id == device.device_id]
    assert len(targets) == 6
    assert [t.lifecycle for t in targets] == ["discovery_only"] * 2 + ["reserve"] * 4
    assert all(t.addresses == (256, 257) for t in targets)
    with pytest.raises(ValueError, match="[Oo]verlap|[Cc]onflict"):
        AcquisitionRegistry(doc).with_xjp60d_enrollment([6], profile_version="dixell-xjp60d-sections-v1-6")
    with pytest.raises(ValueError):
        registry.with_xjp60d_enrollment([243], profile_version="dixell-xjp60d-sections-v1-2")
    # Existing one-address layout keeps its six register pairs.
    legacy, _ = registry.with_xjp60d_enrollment([7])
    assert [t.addresses for t in legacy.targets if t.device_id == "xjp60d-7"] == [(256+2*i,257+2*i) for i in range(6)]


def test_active_section_targets_stay_out_of_legacy_point_compatibility():
    from test_acquisition_registry import settings
    from acquisition_registry import AcquisitionRegistry, build_initial_document, DeviceLifecycleMutation, LifecycleMutation
    registry = AcquisitionRegistry(build_initial_document(settings(), discovery_units=(), legacy_active_points=()))
    doc, _ = registry.with_xjp60d_enrollment([7], profile_version="dixell-xjp60d-sections-v1-2")
    device = next(d for d in doc.devices if d.unit_id == 7)
    registry = AcquisitionRegistry(doc)
    doc, _ = registry.with_mutations(device_mutations=[DeviceLifecycleMutation(device.device_id, "active")],
        target_mutations=[LifecycleMutation(t.target_id,"active") for t in doc.targets if t.device_id==device.device_id and t.lifecycle!="reserve"])
    registry = AcquisitionRegistry(doc)
    assert len(registry.eligible_targets("xjp60d")) == 2
    assert registry.eligible_xjp60d_points() == ()


def test_actual_scheduled_section_dispatch_preserves_physical_group():
    from contextlib import nullcontext
    from types import SimpleNamespace
    from unittest.mock import Mock
    from dual_bus_main import DualBusAdaptiveRegistryDeviceAgent
    from scheduler_policy import SchedulerTarget
    agent = object.__new__(DualBusAdaptiveRegistryDeviceAgent)
    agent.settings = SimpleNamespace(node_id="edge-01")
    agent.rs485_topology = SimpleNamespace(explicit=True, commissioned_bus_ids=frozenset())
    reader = XJP60DReader(SimpleNamespace(read_holding_register=lambda unit, address: 217 if address==256 else 0x1100))
    client = SimpleNamespace(instrumentation_scope=lambda **kw: nullcontext())
    agent._bus_clients = {"rs485-test":client}
    agent._bus_xjp60d_readers = {"rs485-test":reader}
    target = SchedulerTarget("sections:7:2","rs485-test","group7","xjp60d",7,"section-02","rs485-test:7-S02","temperature.probe","degC","high",60)
    result = agent._read_scheduled_target(target)
    assert not result.communication_failed
    assert result.record.quality == "valid"
    assert result.record.equipment_id == "XJP60D-S:rs485-test:7"
    assert result.record.source == "dixell-xjp60d-sections"
    assert result.record.value == pytest.approx(21.7)


def test_section_activation_is_idempotent_and_reserves_survive_restart():
    from test_dual_bus_main import CommissioningActivationRuntimeTests, settings
    from commissioning_activation import CommissioningActivationRequest
    from dual_bus_main import DualBusAdaptiveRegistryDeviceAgent
    case = CommissioningActivationRuntimeTests()
    case.setUp()
    restarted = None
    try:
        case._allow_activation_adapter()
        request = CommissioningActivationRequest("section-test", "activate", "edge-01", "rs485-kk1",
            "/dev/serial/by-id/usb-kk1", 7, "dixell-xjp60d-sections-2", "dixell-xjp60d-sections-v1-2")
        result = case.agent.commissioning_activation(request)
        assert result["state"] == "active" and len(result["target_ids"]) == 2
        assert result["telemetry_equipment_id"] == "XJP60D-S:rs485-kk1:7"
        assert case.agent.commissioning_activation(request) == result
        restarted = DualBusAdaptiveRegistryDeviceAgent(settings(case.database_path))
        registry = restarted._registry_snapshot()
        device = next(d for d in registry.document.devices if d.profile_version==request.profile_version)
        assert device.bus_id == "rs485-kk1"
        targets = [t for t in registry.document.targets if t.device_id==device.device_id]
        assert [t.lifecycle for t in targets] == ["active"]*2+["reserve"]*4
        assert all(t.device_id != device.device_id or int(t.key.split("-")[-1])<=2 for t in registry.eligible_targets())
    finally:
        if restarted:
            for client in restarted._bus_clients.values(): client.close()
        case.tearDown()
