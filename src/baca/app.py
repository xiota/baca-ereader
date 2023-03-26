import os
import subprocess
from dataclasses import asdict
from datetime import datetime
from importlib import resources

from textual import events
from textual.app import App, ComposeResult
from textual.css.query import NoMatches
from textual.widgets import LoadingIndicator

from .components.contents import Content
from .components.events import DoneLoading, FollowThis, OpenThisImage, Screenshot
from .components.windows import Alert, DictDisplay, ToC
from .config import load_user_config
from .ebooks import Ebook, Epub
from .models import KeyMap, ReadingHistory
from .utils.keys_parser import dispatch_key


class Baca(App):
    CSS_PATH = str(resources.path("baca.resources", "style.css"))

    def __init__(self, ebook_path: str):
        self.config = load_user_config()  # load first to resolve colors
        super().__init__()
        # TODO: move initializing ebook to self.load_everything()
        self.ebook_path = ebook_path
        # TODO: make reactive and display percentage
        # as alternative for scrollbar
        self.reading_progress = 0.0

    def on_load(self, _: events.Load) -> None:
        assert self._loop is not None
        self._loop.run_in_executor(None, self.load_everything)

    def load_everything(self):
        self.ebook = Epub(self.ebook_path)
        content = Content(self.config, self.ebook)
        self.ebook_state, _ = ReadingHistory.get_or_create(
            filepath=self.ebook.get_path(), defaults=dict(reading_progress=0.0)
        )
        # NOTE: using a message instead of calling
        # the callback directly to make sure that the app is ready
        # before calling the callback, since this message will
        # get processed after app ready and composed
        # (self._screen_stack isn't empty)
        # see: Widget.on_event(), App._process_message()
        self.post_message(DoneLoading(content))

    async def on_done_loading(self, event: DoneLoading) -> None:
        # to be safe, unnecessary?
        # while self.screen is None:
        #     await asyncio.sleep(0.1)

        # NOTE: await to prevent broken layout
        await self.mount(event.content)

        def init_render() -> None:
            # restore reading progress
            historic_y = self.ebook_state.reading_progress * self.screen.max_scroll_y
            self.screen.scroll_to(None, historic_y, speed=0, animate=False)  # type: ignore

            self.get_widget_by_id("startup-loader", LoadingIndicator).remove()

        self.call_after_refresh(init_render)

    def on_mount(self):
        def screen_watch_scroll_y_wrapper(old_watcher, screen):
            def new_watcher(old, new):
                result = old_watcher(old, new)
                if screen.max_scroll_y != 0:
                    self.reading_progress = new / screen.max_scroll_y
                return result

            return new_watcher

        screen_scroll_y_watcher = getattr(self.screen, "watch_scroll_y")
        setattr(self.screen, "watch_scroll_y", screen_watch_scroll_y_wrapper(screen_scroll_y_watcher, self.screen))

    def get_css_variables(self):
        original = super().get_css_variables()
        return {
            **original,
            **{
                "text-max-width": self.config.max_text_width,
                "text-justification": self.config.text_justification,
                "dark-bg": self.config.dark.bg,
                "dark-fg": self.config.dark.fg,
                "dark-accent": self.config.dark.accent,
                "light-bg": self.config.light.bg,
                "light-fg": self.config.light.fg,
                "light-accent": self.config.light.accent,
            },
        }

    async def on_key(self, event: events.Key) -> None:
        keymaps = self.config.keymaps
        await dispatch_key(
            [
                KeyMap(keymaps.close, self.action_quit),
                KeyMap(keymaps.scroll_down, self.screen.action_scroll_down),
                KeyMap(keymaps.scroll_up, self.screen.action_scroll_up),
                KeyMap(keymaps.page_up, self.screen.action_page_up),
                KeyMap(keymaps.page_down, self.screen.action_page_down),
                KeyMap(keymaps.home, self.screen.action_scroll_home),
                KeyMap(keymaps.end, self.screen.action_scroll_end),
                KeyMap(keymaps.open_toc, self.action_open_toc),
                KeyMap(keymaps.open_metadata, self.action_open_metadata),
                KeyMap(keymaps.open_help, self.action_open_help),
                KeyMap(keymaps.toggle_dark, self.action_toggle_dark),
                KeyMap(keymaps.screenshot, lambda: self.post_message(Screenshot())),
                KeyMap(["D"], lambda: self.log()),
            ],
            event,
        )

    def compose(self) -> ComposeResult:
        yield LoadingIndicator(id="startup-loader")

    async def alert(self, message: str) -> None:
        alert = Alert(self.config, message)
        await self.mount(alert)

    async def action_open_metadata(self) -> None:
        if self.metadata_window is None:
            metadata_window = DictDisplay(
                config=self.config, id="metadata", title="Metadata", data=asdict(self.ebook.get_meta())
            )
            await self.mount(metadata_window)

    async def action_open_help(self) -> None:
        if self.help_window is None:
            keymap_data = {k.replace("_", " ").title(): ",".join(v) for k, v in asdict(self.config.keymaps).items()}
            help_window = DictDisplay(config=self.config, id="help", title="Metadata", data=keymap_data)
            await self.mount(help_window)

    async def action_open_toc(self) -> None:
        if self.toc_window is None:
            toc_entries = list(self.ebook.get_toc())
            if len(toc_entries) == 0:
                return await self.alert("No content navigations for this ebook.")

            initial_focused_id: str | None = None
            for s in self.content.sections:
                if self.screen.scroll_y >= s.virtual_region.y:
                    initial_focused_id = s.id
                else:
                    break

            toc = ToC(self.config, entries=toc_entries, initial_focused_id=initial_focused_id)
            # NOTE: await to prevent broken layout
            await self.mount(toc)

    async def on_follow_this(self, message: FollowThis) -> None:
        self.content.scroll_to_section(message.value)
        # NOTE: remove after refresh so the event get handled
        self.call_after_refresh(self.toc_window.remove)  # type: ignore

    async def on_open_this_image(self, message: OpenThisImage) -> None:
        filename, bytestr = self.ebook.get_img_bytestr(message.value)
        tmpfilepath = os.path.join(self.ebook.get_tempdir(), filename)
        with open(tmpfilepath, "wb") as img_tmp:
            img_tmp.write(bytestr)

        try:
            subprocess.check_output(["xdg-open", tmpfilepath], stderr=subprocess.PIPE)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            error_msg = e.stderr.decode() if isinstance(e, subprocess.CalledProcessError) else str(e)
            await self.alert(f"Error opening an image: {error_msg}")

    async def on_screenshot(self, _: Screenshot) -> None:
        self.save_screenshot(f"baca_{datetime.now().isoformat()}.svg")

    def run(self, *args, **kwargs):
        try:
            return super().run(*args, **kwargs)
        finally:
            self.ebook.cleanup()
            meta = self.ebook.get_meta()
            self.ebook_state.last_read = datetime.now()  # type: ignore
            self.ebook_state.title = meta.title  # type: ignore
            self.ebook_state.author = meta.creator  # type: ignore
            self.ebook_state.reading_progress = self.reading_progress  # type: ignore
            self.ebook_state.save()

    @property
    def toc_window(self) -> ToC | None:
        try:
            return self.query_one(ToC.__name__, ToC)
        except NoMatches:
            return None

    @property
    def metadata_window(self) -> DictDisplay | None:
        try:
            return self.get_widget_by_id("metadata", DictDisplay)
        except NoMatches:
            return None

    @property
    def help_window(self) -> DictDisplay | None:
        try:
            return self.get_widget_by_id("help", DictDisplay)
        except NoMatches:
            return None

    @property
    def content(self) -> Content:
        return self.query_one(Content.__name__, Content)

    # def _remove_nodes(self, widgets: list[Widget], parent: DOMNode) -> AwaitRemove:
    #     await_remove = super()._remove_nodes(widgets, parent)
    #     self.refresh(layout=True)
    #     return await_remove
    # def on_mount(self) -> None:
    #     self.screen.can_focus = True
