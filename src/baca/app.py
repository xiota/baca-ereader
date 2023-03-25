import os
import subprocess
from datetime import datetime

from textual import events
from textual.app import App, ComposeResult
from textual.await_remove import AwaitRemove
from textual.css.query import NoMatches
from textual.dom import DOMNode
from textual.widget import Widget
from textual.widgets import LoadingIndicator

from .components.contents import Content
from .components.events import DoneLoading, FollowThis, OpenThisImage
from .components.windows import Alert, Metadata, ToC
from .config import load_config
from .ebooks import Ebook
from .models import KeyMap, Layers
from .utils.keys_parser import dispatch_key


# TODO: reorganize methods order
class Baca(App):
    def __init__(self, ebook: Ebook):
        super().__init__()
        # TODO: move initializing ebook to self.load_everything()
        self.ebook = ebook

    def on_load(self, _: events.Load) -> None:
        assert self._loop is not None
        self._loop.run_in_executor(None, self.load_everything)

    def load_everything(self):
        self.config = load_config()
        content = Content(self.config, self.ebook)
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

        # NOTE: awaiting is necessary to prevent broken layout
        await self.mount(event.content)
        self.get_widget_by_id("startup-loader", LoadingIndicator).remove()

    async def alert(self, message: str) -> None:
        alert = Alert(self.config, message)
        await self.mount(alert)

    async def on_key(self, event: events.Key) -> None:
        cfgkeymaps = self.config.keymaps
        keymaps = [
            KeyMap(cfgkeymaps.close, self.action_quit),
            KeyMap(cfgkeymaps.scroll_down, self.screen.action_scroll_down),
            KeyMap(cfgkeymaps.scroll_up, self.screen.action_scroll_up),
            KeyMap(cfgkeymaps.page_up, self.screen.action_page_up),
            KeyMap(cfgkeymaps.page_down, self.screen.action_page_down),
            KeyMap(cfgkeymaps.open_toc, self.action_open_toc),
            KeyMap(cfgkeymaps.open_metadata, self.action_open_metadata),
            KeyMap(cfgkeymaps.toggle_dark, self.action_toggle_dark),
            KeyMap(cfgkeymaps.screenshot, lambda: self.save_screenshot(f"baca_{datetime.now().isoformat()}.svg")),
            KeyMap(["D"], self.debug),
        ]
        await dispatch_key(keymaps, event)

    def on_mount(self) -> None:
        # self.styles.background =None
        # self.screen.styles.background = "transparent"
        self.screen.styles.align = ("center", "middle")
        self.screen.styles.scrollbar_size_vertical = 1
        self.screen.styles.layers = (layer.value for layer in Layers)
        self.screen.can_focus = True

    # TODO: move this to self.screen
    # async def on_click(self):
    #     self.query("Window").remove()

    def compose(self) -> ComposeResult:
        yield LoadingIndicator(id="startup-loader")

    async def action_open_metadata(self) -> None:
        if self.metadata is None:
            metadata = Metadata(self.config, self.ebook.get_meta())
            await self.mount(metadata)

    async def action_open_toc(self) -> None:
        if self.toc is None:
            toc_entries = list(self.ebook.get_toc())
            if len(toc_entries) == 0:
                return await self.alert("No content navigations for this ebook.")

            initial_focused_id: str | None = None
            for s in self.content.sections:
                if self.screen.scroll_y >= s.virtual_region.y:
                    initial_focused_id = s.id
                # TODO: check why breaking here not working
                # else:
                #     break

            toc = ToC(self.config, entries=toc_entries, initial_focused_id=initial_focused_id)
            # NOTE: awaiting is necessary to prevent broken layout
            await self.mount(toc)

    async def on_follow_this(self, message: FollowThis) -> None:
        self.content.scroll_to_section(message.value)
        # NOTE: remove after refresh so the event get handled
        self.call_after_refresh(self.toc.remove)  # type: ignore

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

    def _remove_nodes(self, widgets: list[Widget], parent: DOMNode) -> AwaitRemove:
        await_remove = super()._remove_nodes(widgets, parent)
        self.refresh(layout=True)
        return await_remove

    def run(self, *args, **kwargs):
        try:
            return super().run(*args, **kwargs)
        finally:
            self.ebook.cleanup()

    @property
    def toc(self) -> ToC | None:
        try:
            return self.query_one(ToC.__name__, ToC)
        except NoMatches:
            return None

    @property
    def metadata(self) -> Metadata | None:
        try:
            return self.query_one(Metadata.__name__, Metadata)
        except NoMatches:
            return None

    @property
    def content(self) -> Content:
        return self.query_one(Content.__name__, Content)

    def debug(self) -> None:
        self.log(None)
