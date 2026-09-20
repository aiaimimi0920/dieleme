import threading
from types import SimpleNamespace

from tools.pc2_engine_controller import EngineController
from tools.test.test_pc2_engine_controller import containers, output


def test_restart_does_not_serialize_worker_stop_grace_periods():
    rendezvous = threading.Barrier(8, timeout=5)
    restarted = threading.Event()

    def run(arguments, *, timeout):
        if arguments[0] == "restart":
            assert len(arguments) == 4
            assert timeout == 60
            rendezvous.wait()
            restarted.set()
            return SimpleNamespace(stdout="")
        return output(arguments, containers(started="after" if restarted.is_set() else "before"))

    assert EngineController(run=run).restart() == "workers_ready"
