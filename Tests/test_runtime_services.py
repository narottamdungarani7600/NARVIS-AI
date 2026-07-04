"""Tests for the stable runtime service integrations added in NARVIS v1.0."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from unittest import mock
from pathlib import Path
import shutil
from uuid import uuid4

from Automation import AutomationAction, build_automation_services
from Core.optimization import RuntimeOptimizationService
from Internet import SearchResult, build_internet_services
from Memory import build_memory_integration_service, build_memory_services
import narvis
from narvis import NARVISApplication


def _workspace_temp_dir() -> str:
    """Create a temporary directory inside the writable workspace."""

    root = Path.cwd() / "data" / "test_runtime_tmp"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"case_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


class _FakeSearchProvider:
    """Search provider stub that records how often it is queried."""

    def __init__(self) -> None:
        self.calls = 0

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        self.calls += 1
        return [SearchResult(title=f"Result for {query}", url=f"https://example.com/{query.replace(' ', '-')}")]


class RuntimeAutomationTests(unittest.TestCase):
    """Verify automation runtime services remain safe and deterministic."""

    def test_workspace_file_actions_round_trip_text(self) -> None:
        temp_dir = _workspace_temp_dir()
        self.addCleanup(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
        services = build_automation_services(workspace_root=temp_dir)

        write_result = services.automation_service.execute(
            AutomationAction(name="file.write_text", payload={"path": "notes\\memo.txt", "content": "stable release"})
        )
        read_result = services.automation_service.execute(
            AutomationAction(name="file.read_text", payload={"path": "notes\\memo.txt"})
        )

        self.assertTrue(write_result.success)
        self.assertTrue(read_result.success)
        self.assertEqual(read_result.data["content"], "stable release")

    def test_workspace_file_actions_reject_escape_paths(self) -> None:
        temp_dir = _workspace_temp_dir()
        self.addCleanup(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
        services = build_automation_services(workspace_root=temp_dir)
        outside_path = Path(temp_dir).parent / "escape.txt"

        result = services.automation_service.execute(
            AutomationAction(name="file.write_text", payload={"path": str(outside_path), "content": "blocked"})
        )

        self.assertFalse(result.success)
        self.assertIn("outside the workspace root", result.error or "")


class RuntimeInternetTests(unittest.TestCase):
    """Verify internet runtime helpers add caching on top of providers."""

    def test_internet_service_caches_search_results(self) -> None:
        provider = _FakeSearchProvider()
        runtime_optimizer = RuntimeOptimizationService()
        services = build_internet_services(search_provider=provider, runtime_optimizer=runtime_optimizer)

        first = services.internet_service.search("narvis stable", limit=5)
        second = services.internet_service.search("narvis stable", limit=5)
        history = services.internet_service.history()

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(provider.calls, 1)
        self.assertFalse(history[0].cached)
        self.assertTrue(history[1].cached)


class RuntimeMemoryIntegrationTests(unittest.TestCase):
    """Verify the new memory integration service coordinates storage cleanly."""

    def test_memory_integration_tracks_scope_and_history_counts(self) -> None:
        temp_dir = _workspace_temp_dir()
        self.addCleanup(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
        memory_services = build_memory_services(database_path=Path(temp_dir) / "memory.sqlite3")
        memory_integration = build_memory_integration_service(
            storage=memory_services.storage,
            short_term_memory=memory_services.short_term_memory,
            long_term_memory=memory_services.long_term_memory,
            session_memory=memory_services.session_memory,
            profile_memory=memory_services.profile_memory,
            memory_search=memory_services.memory_search,
        )

        memory_integration.remember("favorite_drink", "tea", scope="both", metadata={"source": "user"})
        memory_integration.store_conversation_turn(
            session_id="session-1",
            conversation_id="conv-1",
            role="user",
            content="remember tea",
        )
        snapshot = memory_integration.snapshot_counts()

        self.assertEqual(snapshot.short_term_entries, 1)
        self.assertEqual(snapshot.long_term_entries, 1)
        self.assertEqual(snapshot.conversation_history_entries, 1)
        self.assertGreaterEqual(snapshot.total_entries, 3)


class RuntimeApplicationIntegrationTests(unittest.TestCase):
    """Verify the application exposes the new stable runtime services."""

    def _build_test_application(self) -> NARVISApplication:
        temp_dir = Path(_workspace_temp_dir())
        self.addCleanup(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
        data_dir = temp_dir / "data"
        log_dir = temp_dir / "logs"
        data_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)
        return NARVISApplication(config=narvis.NARVISConfig(data_dir=data_dir, log_dir=log_dir))

    def test_narvis_application_registers_new_runtime_services(self) -> None:
        application = self._build_test_application()
        try:
            application.start()
            health = application.health()
            dashboard = application.container.resolve("dashboard")
            skill_registry = application.container.resolve("skill_registry")
            desktop_command_skill = skill_registry.resolve("desktop.command")
            plugin_registry = application.container.resolve("plugin_registry")
            memory_service = application.container.resolve("memory_service")
            internet_service = application.container.resolve("internet_service")
            automation_service = application.container.resolve("automation_service")
            desktop_control = application.container.resolve("desktop_control")
            desktop_command_pipeline = application.container.resolve("desktop_command_pipeline")
            application_resolver = application.container.resolve("application_resolver")
            universal_open_resolver = application.container.resolve("universal_open_resolver")
            universal_open_launcher = application.container.resolve("universal_open_launcher")
            runtime_optimizer = application.container.resolve("runtime_optimizer")
        finally:
            application.shutdown()

        self.assertGreaterEqual(skill_registry.count(), 5)
        self.assertEqual(desktop_command_skill.name, "desktop.command")
        self.assertGreaterEqual(plugin_registry.loaded_count(), 4)
        self.assertIsNotNone(dashboard)
        self.assertIsNotNone(memory_service)
        self.assertIsNotNone(internet_service)
        self.assertIsNotNone(automation_service)
        self.assertIsNotNone(desktop_control)
        self.assertIsNotNone(desktop_command_pipeline)
        self.assertIsNotNone(application_resolver)
        self.assertIsNotNone(universal_open_resolver)
        self.assertIsNotNone(universal_open_launcher)
        self.assertIsNotNone(runtime_optimizer)
        self.assertIn("skills", health)
        self.assertIn("plugins", health)

    def test_process_text_async_launches_cmd_exactly_once(self) -> None:
        application = self._build_test_application()
        try:
            application.start()
            application_manager = application.container.resolve("application_manager")
            with mock.patch.object(application_manager, "open_app_by_name", return_value=True) as open_app:
                response = asyncio.run(application.process_text_async("Open CMD"))
        finally:
            application.shutdown()

        self.assertEqual(open_app.call_count, 1)
        open_app.assert_called_once_with("CMD")
        self.assertEqual(response, "Opened application 'CMD'.")

    def test_narvis_module_main_processes_console_commands_and_shuts_down(self) -> None:
        application = _FakeApplication()

        with mock.patch.object(narvis, "NARVISApplication", return_value=application), mock.patch(
            "builtins.input",
            side_effect=["", "status", "exit"],
        ), mock.patch("builtins.print") as print_mock:
            exit_code = asyncio.run(narvis.main())

        self.assertEqual(exit_code, 0)
        self.assertTrue(application.started)
        self.assertEqual(application.processed_commands, ["status"])
        self.assertTrue(application.shutdown_called)
        print_mock.assert_any_call("NARVIS Ready.")
        print_mock.assert_any_call("Type commands (type 'exit' to quit).")
        print_mock.assert_any_call("handled: status")

    def test_narvis_module_main_accepts_multiple_sequential_commands_once_each(self) -> None:
        application = _FakeApplication()
        console = _ScriptedConsole(["Open Photoshop", "Open CorelDRAW", "Open Calculator", "exit"])

        with mock.patch.object(narvis, "NARVISApplication", return_value=application):
            exit_code = asyncio.run(
                narvis.main(
                    input_reader=console.read_input,
                    output_writer=console.write_output,
                )
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            application.processed_commands,
            ["Open Photoshop", "Open CorelDRAW", "Open Calculator"],
        )
        self.assertEqual(
            console.outputs,
            [
                "NARVIS Ready.",
                "Type commands (type 'exit' to quit).",
                "handled: Open Photoshop",
                "handled: Open CorelDRAW",
                "handled: Open Calculator",
            ],
        )
        self.assertEqual(console.prompts, ["> ", "> ", "> ", "> "])
        self.assertTrue(application.shutdown_called)

    def test_narvis_module_main_keeps_session_alive_until_explicit_exit(self) -> None:
        application = _FakeApplication()
        console = _ScriptedConsole(["Open Photoshop", "exit"])

        with mock.patch.object(narvis, "NARVISApplication", return_value=application):
            exit_code = asyncio.run(
                narvis.main(
                    input_reader=console.read_input,
                    output_writer=console.write_output,
                )
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(application.processed_commands, ["Open Photoshop"])
        self.assertEqual(console.prompts, ["> ", "> "])
        self.assertTrue(application.shutdown_called)


class _FakeLogger:
    """Logger stub used by the module entry point test."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def log(self, level, message: str, **context) -> None:
        self.messages.append(message)


class _FakeApplication:
    """Application stub used to validate the narvis module entry point."""

    def __init__(self) -> None:
        self.started = False
        self.shutdown_called = False
        self.logger = _FakeLogger()
        self.processed_commands: list[str] = []

    async def async_start(self) -> None:
        self.started = True

    async def process_text_async(self, text: str) -> str:
        self.processed_commands.append(text)
        return f"handled: {text}"

    async def async_shutdown(self) -> None:
        self.shutdown_called = True


class _ScriptedConsole:
    """Console stub that records prompts and emitted output."""

    def __init__(self, inputs: list[str]) -> None:
        self._inputs = list(inputs)
        self.prompts: list[str] = []
        self.outputs: list[str] = []

    def read_input(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._inputs:
            raise EOFError
        return self._inputs.pop(0)

    def write_output(self, message: str) -> None:
        self.outputs.append(message)


if __name__ == "__main__":
    unittest.main()
