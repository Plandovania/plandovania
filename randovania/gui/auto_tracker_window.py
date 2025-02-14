import collections
import functools
import json
from pathlib import Path

from PySide6 import QtWidgets, QtGui

from randovania import get_data_path
from randovania.game_connection.builder.connector_builder import ConnectorBuilder
from randovania.game_connection.game_connection import GameConnection, ConnectedGameState
from randovania.games.game import RandovaniaGame
from randovania.gui.generated.auto_tracker_window_ui import Ui_AutoTrackerWindow
from randovania.gui.lib import common_qt_lib
from randovania.gui.lib.window_manager import WindowManager
from randovania.gui.widgets.item_tracker_widget import ItemTrackerWidget
from randovania.interface_common.options import Options


def load_trackers_configuration() -> dict[RandovaniaGame, dict[str, Path]]:
    with get_data_path().joinpath("gui_assets/tracker/trackers.json").open("r") as trackers_file:
        data = json.load(trackers_file)["trackers"]

    return {
        RandovaniaGame(game): {
            name: get_data_path().joinpath("gui_assets/tracker", file_name)
            for name, file_name in trackers.items()
        }
        for game, trackers in data.items()
    }


class AutoTrackerWindow(QtWidgets.QMainWindow, Ui_AutoTrackerWindow):
    trackers: dict[RandovaniaGame, dict[str, Path]]
    _tracker_actions: dict[RandovaniaGame, list[QtGui.QAction]]
    _full_name_to_path: dict[str, Path]
    _connected_game: RandovaniaGame | None = None
    _current_tracker_game: RandovaniaGame | None = None
    _current_tracker_name: str = "undefined"
    item_tracker: ItemTrackerWidget | None = None
    _dummy_tracker: QtWidgets.QWidget | None = None

    def __init__(self, game_connection: GameConnection, window_manager: WindowManager | None, options: Options):
        super().__init__()
        self.setupUi(self)
        self.game_connection = game_connection
        self.options = options
        common_qt_lib.set_default_window_icon(self)

        self.trackers = load_trackers_configuration()
        self._tracker_actions = collections.defaultdict(list)

        for game in sorted(self.trackers.keys(), key=lambda k: k.long_name):
            game_menu = QtWidgets.QMenu(self.menu_tracker)
            game_menu.setTitle(game.long_name)
            self.menu_tracker.addMenu(game_menu)
            for name in sorted(self.trackers[game].keys()):
                action = QtGui.QAction(game_menu)
                action.setText(name)
                action.setCheckable(True)
                action.setChecked(name == options.selected_tracker_for(game))
                action.triggered.connect(functools.partial(self._on_action_select_tracker, game, name))
                game_menu.addAction(action)
                self._tracker_actions[game].append(action)

        if window_manager is None:
            self.select_game_button.setVisible(False)
        else:
            self.select_game_button.clicked.connect(window_manager.open_game_connection_window)
        self.select_game_combo.currentIndexChanged.connect(self.create_tracker)
        self.game_connection.BuildersChanged.connect(self.update_sources_combo)
        self.game_connection.GameStateUpdated.connect(self.on_game_state_updated)
        self.update_sources_combo()

    def selected_tracker_for(self, game: RandovaniaGame) -> str:
        actions = [action for action in self._tracker_actions[game] if action.isChecked()]
        if not actions:
            actions = self._tracker_actions[game]

        return actions[0].text()

    def _on_action_select_tracker(self, game: RandovaniaGame, name: str):
        with self.options as options:
            options.set_selected_tracker_for(game, name)
        self.create_tracker()

    def delete_tracker(self):
        if self.item_tracker is not None:
            self.item_tracker.deleteLater()
            self.item_tracker = None

        if self._dummy_tracker is not None:
            self._dummy_tracker.deleteLater()
            self._dummy_tracker = None

    def create_tracker(self):
        connector = self.game_connection.get_connector_for_builder(self.selected_builder())
        tracker_name = None
        target_game = None

        if connector is not None:
            target_game = connector.game_enum
            tracker_name = self.selected_tracker_for(target_game)

        if tracker_name == self._current_tracker_name and target_game == self._current_tracker_game:
            return

        self.delete_tracker()

        if target_game is None:
            self._dummy_tracker = QtWidgets.QLabel(
                "Not currently connected to any games",
                self
            )
            self.gridLayout.addWidget(self._dummy_tracker, 0, 0, 1, 1)
        else:
            with self.trackers[target_game][tracker_name].open("r") as tracker_details_file:
                tracker_details = json.load(tracker_details_file)

            self.item_tracker = ItemTrackerWidget(tracker_details)
            self.gridLayout.addWidget(self.item_tracker, 0, 0, 1, 1)
            state = self.game_connection.connected_states.get(connector)
            if state is not None:
                self.item_tracker.update_state(state.current_inventory)

        self._current_tracker_game = target_game
        self._current_tracker_name = tracker_name

    def update_sources_combo(self):
        old_builder = self.selected_builder()
        self.select_game_combo.clear()

        index_to_select = None
        for i, builder in enumerate(self.game_connection.connection_builders):
            if builder == old_builder:
                index_to_select = i
            self.select_game_combo.addItem(
                builder.pretty_text,
                builder,
            )

        if not self.game_connection.connection_builders:
            self.select_game_combo.addItem(
                "No sources available"
            )
        if index_to_select is not None:
            self.select_game_combo.setCurrentIndex(index_to_select)

        self.create_tracker()

    def selected_builder(self) -> ConnectorBuilder | None:
        return self.select_game_combo.currentData()

    def on_game_state_updated(self, state: ConnectedGameState):
        expected_connector = self.game_connection.get_connector_for_builder(self.selected_builder())
        if expected_connector == state.source:
            self.item_tracker.update_state(state.current_inventory)
