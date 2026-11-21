# Local EAB changes

Base: upstream tag `v1.7.7` (`c453a79b7be276793bbf4c34f6f282299573342c`).
Working branch: `feature/daily-arena`.
`origin` points to `moonjoungyoung/EAB`; `upstream` points to `pelierze/EAB`.

## Patch groups

1. Exploration recognition (`src/chaos/node_layout.json`): mask the animated purple defeat effects and the lower rim of battle-node markers. Preserve thresholds and other configuration.
2. Recruitment memory (`src/chaos/recruitment_layout.json`): restrict element-filter matching to the filter row instead of the full screen.
3. Daily NPC arena: `ArenaBot`, `ArenaObserver`, the Daily Tasks tab, runtime image assets and regression tests. No changes to the remote macro registry are needed.

## Updating the fork

Fetch upstream branches and tags first. Compare each patch group with the target release before rebasing, since upstream may already contain equivalent fixes. In particular, keep arena UI changes in the Daily Tasks section rather than rewriting unrelated GUI code.

The checkout is based on 1.7.7. Upstream 1.7.8 was discovered during fork setup but has not been merged or rebased into this branch. A future rebase requires a new build and verification against the game; replacing the executable with an official release would remove the local arena feature.

## Verification and packaging

Use Python 3.12 and `requirements.txt`, then install `pytest` and `pyinstaller` in a virtual environment.

```powershell
python -m unittest discover -s tests -p 'test_arena*.py'
python -m unittest discover -s tests -p 'test_gui*.py'
python -m unittest discover -s tests -p 'test_scrollable_gui.py'
python -m unittest discover -s tests -p 'test_release_assets.py'
python -m PyInstaller --noconfirm EAB.spec
python -m build_support.release_assets --validate dist/EAB --profile build
```

Arena fixtures retain only the image regions used by recognition; player names and unrelated game content are removed. Recognition assets contain icons and button edges, not words or counters. `tools/build_arena_assets.py` records the capture crop coordinates; its original full captures are local, ignored development artifacts.

Live verification: ten NPC quick battles completed, including the unequipped-hero dialog. After refining recognition against the actual exhausted-quota screen, a subsequent run confirmed normal completion without clicking the ordinary battle button. Runtime package validation and GUI startup acknowledgement also passed.

The screen-protector recognizer currently covers the recorded lobby background. Other backgrounds should have their menu revealed before starting. Unknown dialogs stop safely with a diagnostic image.
