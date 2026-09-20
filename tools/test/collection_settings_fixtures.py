"""Offline synthetic settings and Docker inputs; never read real credentials."""
from copy import deepcopy
import hashlib
import json

from tools.pc2_settings_model import inventory, literal_compose, STAGES, workers


def model_fixture():
    services = {"pc2-browser-solver": {"image": "browser:fixture", "environment": {"KEEP_BROWSER": "yes"}}}
    for stage, role in STAGES.items():
        for index in range(1, {"links": 1, "details": 3, "analysis": 4}[stage] + 1):
            output = {"links": "seed_collector", "details": "detail_worker", "analysis": "detail_analysis_worker"}[stage]
            env = {"FAPAI_RUN_MODE": role, "KEEP_UNRELATED": "literal-$fixture",
                   "FAPAI_OUTPUT_DIR": "/data/output/" + output + (f"_{index}" if index > 1 else ""),
                   "FAPAI_SEED_WORKER_ID" if stage == "links" else "FAPAI_DETAIL_WORKER_ID": f"{role}-{index}"}
            if stage == "analysis":
                env.update(OPENAI_BASE_URL="https://ai.example.invalid/v1", OPENAI_MODEL="deepseek-fixture",
                           OPENAI_MODEL_CANDIDATES="deepseek-fixture,other-fixture", OPENAI_API_KEY="synthetic-key-not-real")
            name = f"pc2-{role}-{index}"
            services[name] = {"image": "worker:fixture", "container_name": "fapaifang-" + name,
                              "environment": env, "volumes": [{"type": "bind", "source": "/fixture/data", "target": "/data/output"}],
                              "networks": {"default": None}}
    return {"name": "fapaifang-pc2", "services": services, "networks": {"default": {"name": "fapaifang-pc2_default"}}}


def config_fixture():
    return inventory(model_fixture())["effective"]


class FakeDocker:
    def __init__(self, *, fail_new=False, fail_rollback=False):
        self.model = model_fixture()
        self.rows = {}
        self.calls = []
        self.time = 0
        self.fail_new, self.fail_rollback = fail_new, fail_rollback
        for name, service in workers(self.model).items():
            self.start(name, service)

    def start(self, name, service, healthy=True):
        self.rows[name] = {"Id": hashlib.sha256(name.encode()).hexdigest(), "Name": "/fapaifang-" + name, "Image": "sha256:" + "a" * 64,
                           "Config": {"Image": service["image"], "Env": [key + "=" + str(value) for key, value in service["environment"].items()],
                                      "Labels": {"com.docker.compose.project": "fapaifang-pc2", "com.docker.compose.service": name}},
                           "State": {"Running": True, "Health": {"Status": "healthy" if healthy else "unhealthy"}},
                           "Mounts": [{"Type": "bind", "Source": "/fixture/data", "Destination": "/data/output", "RW": True}]}

    def sleep(self, seconds):
        self.time += seconds

    def __call__(self, args, timeout=60):
        self.calls.append(args)
        if args[0] == "ps":
            return "\n".join(row["Id"] for row in self.rows.values())
        if args[0] == "inspect":
            return json.dumps(list(self.rows.values()))
        if args[0] == "stop":
            for row in self.rows.values():
                if row["Id"] in args[3:]:
                    row["State"]["Running"] = False
            return ""
        if args[0] != "compose":
            raise AssertionError("Unexpected Docker mutation: " + args[0])
        if "--format" in args:
            return json.dumps(self.model)
        if "--quiet" in args:
            return ""
        assert "up" in args and "--no-deps" in args and "--no-build" in args
        from pathlib import Path
        path = Path(args[args.index("-f") + 1])
        # Model the one Compose interpolation pass, not shell execution.
        model = json.loads(path.read_text().replace("$$", "$"))
        names = args[args.index("--no-build") + 1:]
        for name in names:
            self.start(name, model["services"][name], healthy=not (self.fail_new if path.name == "after.json" else self.fail_rollback))
        return ""
