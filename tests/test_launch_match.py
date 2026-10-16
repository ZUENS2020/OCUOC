from types import SimpleNamespace

from ocuoc.wm.launch import launch_aliases, window_matches_launch
from ocuoc.wm.processes import descendant_pids


def test_descendant_pids_walks_tree():
    rows = [
        (10, 1, "steam.exe"),
        (50, 10, "steamwebhelper.exe"),
        (51, 50, "steamwebhelper.exe"),
        (90, 2, "unrelated.exe"),
    ]
    kids = descendant_pids(10, rows)
    assert kids == {50, 51}


def test_steam_child_window_matches_parent_pid():
    info = SimpleNamespace(
        pid=50,
        exe=r"C:\Program Files\Steam\steamwebhelper.exe",
        title="Steam",
        class_name="SDL_app",
    )
    assert window_matches_launch(
        info,
        root_pid=10,
        descendant_pids={50, 51},
        stem="steam",
        aliases=launch_aliases("steam"),
    )


def test_title_alias_matches_login_window():
    info = SimpleNamespace(pid=99, exe=r"C:\steam\steam.exe", title="登录 Steam", class_name="#32770")
    assert window_matches_launch(info, root_pid=1, descendant_pids=set(), stem="steam")
