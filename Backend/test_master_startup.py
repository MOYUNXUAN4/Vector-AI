import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent
INTEGRATION = ROOT / "parallel_20261011" / "realtime_integration"
sys.path.insert(0, str(INTEGRATION))
import bridge


def import_master_with_stubs():
    modules = {
        name: types.ModuleType(name)
        for name in ("login_server", "UDPRecevier", "runningball_ai", "car_backend")
    }
    modules["UDPRecevier"].start_backend = lambda **kwargs: None
    with mock.patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location("master_server_test", ROOT / "master_server.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module, modules


class MasterStartupTests(unittest.TestCase):
    def tearDown(self):
        for key in ("FALLING_WARNING_MODEL_ENABLED", "FALLING_WARNING_ALLOW_CALIBRATION_GAMEPLAY"):
            os.environ.pop(key, None)

    def test_default_preloads_and_passes_same_bridge(self):
        master, modules = import_master_with_stubs()
        seen = []

        class FakeBridge:
            def __init__(self, *, enabled, allow_calibration_gameplay):
                self.enabled = enabled
                self.allow_calibration_gameplay = allow_calibration_gameplay

            def preload(self):
                return {"enabled": self.enabled, "loaded": True, "model_id": "test", "reason": "loaded"}

        with mock.patch.object(bridge, "RealtimeWarningBridge", FakeBridge), \
                mock.patch.object(modules["UDPRecevier"], "start_backend", side_effect=lambda warning_bridge=None: seen.append(warning_bridge)), \
                mock.patch("builtins.print"):
            master.run_falling_server()
        self.assertEqual(len(seen), 1)
        self.assertIsInstance(seen[0], FakeBridge)
        self.assertTrue(seen[0].enabled)
        self.assertTrue(seen[0].allow_calibration_gameplay)

    def test_explicit_model_off_skips_load_but_runs_legacy(self):
        master, modules = import_master_with_stubs()
        os.environ["FALLING_WARNING_MODEL_ENABLED"] = "off"
        calls = []

        class FakeBridge:
            def __init__(self, *, enabled, allow_calibration_gameplay):
                self.enabled = enabled

            def preload(self):
                calls.append("preload")
                return {"enabled": False, "loaded": False, "model_id": None, "reason": "disabled"}

        with mock.patch.object(bridge, "RealtimeWarningBridge", FakeBridge), \
                mock.patch.object(modules["UDPRecevier"], "start_backend", side_effect=lambda **kw: calls.append("legacy")), \
                mock.patch("builtins.print"):
            master.run_falling_server()
        self.assertEqual(calls, ["preload", "legacy"])

    def test_failed_preload_does_not_block_legacy(self):
        master, modules = import_master_with_stubs()
        calls = []

        class FakeBridge:
            def __init__(self, **kwargs):
                pass

            def preload(self):
                return {"enabled": True, "loaded": False, "reason": "model_load_failed:OSError"}

        with mock.patch.object(bridge, "RealtimeWarningBridge", FakeBridge), \
                mock.patch.object(modules["UDPRecevier"], "start_backend", side_effect=lambda **kw: calls.append(kw["warning_bridge"])), \
                mock.patch("builtins.print"):
            master.run_falling_server()
        self.assertEqual(len(calls), 1)

    def test_unexpected_preload_exception_disables_bridge_and_runs_legacy(self):
        master, modules = import_master_with_stubs()
        passed = []

        class FakeBridge:
            enabled = True

            def preload(self):
                raise RuntimeError("unexpected preload error")

        instance = FakeBridge()
        with mock.patch.object(master, "_master_warning_bridge", return_value=instance), \
                mock.patch.object(modules["UDPRecevier"], "start_backend", side_effect=lambda warning_bridge=None: passed.append(warning_bridge)), \
                mock.patch("builtins.print"):
            master.run_falling_server()
        self.assertFalse(instance.enabled)
        self.assertEqual(passed, [instance])

    def test_calibration_flag_is_independent(self):
        master, _ = import_master_with_stubs()
        os.environ["FALLING_WARNING_ALLOW_CALIBRATION_GAMEPLAY"] = "false"
        with mock.patch.object(bridge, "RealtimeWarningBridge") as factory:
            master._master_warning_bridge()
        self.assertEqual(factory.call_args.kwargs, {"enabled": True, "allow_calibration_gameplay": False})

    def test_direct_environment_bridge_stays_off_by_default(self):
        direct = bridge.bridge_from_environment()
        self.assertFalse(direct.enabled)

    def test_explicit_off_does_not_construct_runtime(self):
        os.environ["FALLING_WARNING_MODEL_ENABLED"] = "0"
        master, _ = import_master_with_stubs()
        with mock.patch.object(bridge, "RealtimeWarningBridge") as factory:
            master._master_warning_bridge()
        self.assertFalse(factory.call_args.kwargs["enabled"])
        runtime_factory = mock.Mock(side_effect=AssertionError("runtime must not be created"))
        result = bridge.RealtimeWarningBridge(enabled=False, runtime_factory=runtime_factory).preload()
        self.assertFalse(result["loaded"])
        runtime_factory.assert_not_called()

    def test_native_model_preloads_once_and_session_reuses_it(self):
        instance = bridge.RealtimeWarningBridge(enabled=True)
        result = instance.preload()
        self.assertTrue(result["enabled"])
        self.assertTrue(result["loaded"], result)
        self.assertTrue(result["model_id"])
        runtime = instance.runtime
        self.assertIsNotNone(runtime._model)
        self.assertEqual(runtime._model.sha256, bridge.PINNED_MODEL_SHA256)
        with mock.patch.object(runtime, "load", wraps=runtime.load) as load:
            instance.start_session("startup-test-run")
        load.assert_not_called()
        self.assertIs(instance.runtime, runtime)


if __name__ == "__main__":
    unittest.main()
