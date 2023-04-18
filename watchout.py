import sys
import argparse
import asyncio
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent, FileModifiedEvent


class EventTs(asyncio.Event):

    def set(self):
        # asyncio.get_running_loop().call_soon_threadsafe(super().set)
        self._loop.call_soon_threadsafe(super().set)

    def clear(self):
        # asyncio.get_running_loop().call_soon_threadsafe(super().clear)
        self._loop.call_soon_threadsafe(super().clear)


class ProcessRunner:

    def __init__(self, command: str, restart_ev: EventTs) -> None:
        self.commad = command
        self.restart_ev = restart_ev
        self.process = None
        self.running = False

    async def spawn_process(self) -> None:
        self.process = await asyncio.create_subprocess_shell(
            self.commad,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.running = True

    async def terminate_process(self) -> None:
        if self.process:

            if self.process.returncode is None:
                self.process.kill()
                ret = await self.process.wait()

        self.running = False
        return

    async def start(self) -> None:

        await self.terminate_process()
        await self.spawn_process()

        while True:

            if self.running:

                stdout_task = asyncio.create_task(
                    self.process.stdout.readline())
                stderr_task = asyncio.create_task(
                    self.process.stderr.readline())
                event_task = asyncio.create_task(self.restart_ev.wait())

                done, pending = await asyncio.wait(
                    [stdout_task, stderr_task, event_task,],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if event_task in done:
                    await self.terminate_process()
                    await self.spawn_process()
                    self.restart_ev.clear()
                    continue

                if stdout_task in done:
                    if stdout_task.result() == b'':
                        self.running = False
                        continue
                    print(stdout_task.result().decode(),
                          file=sys.stdout, end='')

                if stderr_task in done:
                    if stderr_task.result() == b'':
                        self.running = False
                        continue
                    print(stderr_task.result().decode(),
                          file=sys.stderr, end='')

                for ptask in pending:
                    ptask.cancel()

            else:
                await self.restart_ev.wait()
                await self.terminate_process()
                await self.spawn_process()
                self.restart_ev.clear()


# Define the event handler for file system events
class FileChangedHandler(FileSystemEventHandler):

    def __init__(self, restart_ev: EventTs, file_extensions: list[str] | None):
        self.restart_ev = restart_ev
        self.file_extensions = file_extensions

    def on_modified(self, file_ev: FileSystemEvent):

        # Skip directory events
        if file_ev.is_directory:
            return

        if file_ev.event_type == FileModifiedEvent.event_type:

            trigger_restart = False

            if self.file_extensions:
                for file_extension in self.file_extensions:
                    if file_ev.src_path.endswith(file_extension):
                        trigger_restart = True
            else:
                trigger_restart = True

            if trigger_restart:
                print(f'WATCHIT: Detected file change "{file_ev.src_path}". Restarting ...',
                      file=sys.stderr)
                self.restart_ev.set()

        return


if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description="""Watchit runs a command in a subprocess,
                watches for file changes in a directory,
                and restarts the subprocess when changes occur.""",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-d", "--directory",
                        help="directory to watch", default="./")
    parser.add_argument("-e", "--file-extensions",
                        help="watch only files with these extensions", nargs="*")
    parser.add_argument("-c", "--command",
                        help="Command to run", required=True)
    args = parser.parse_args()
    config = vars(args)

    restart_ev = EventTs()

    process_runner = ProcessRunner(config["command"], restart_ev)

    # Create an observer to watch for file system events
    file_changed_handler = FileChangedHandler(
        restart_ev, config["file_extensions"])
    observer = Observer()
    observer.schedule(
        file_changed_handler,
        path=config["directory"],
        recursive=True)
    observer.start()

    try:
        asyncio.run(process_runner.start())

    except KeyboardInterrupt:
        observer.stop()

    observer.join()
