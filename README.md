# Code and Cosmos

Two animated night looks for the Claude Code desktop app: falling **code rain**, or a **black hole in deep space**. Switch with `/look rain`, `/look space`, or `/look off`.

Built in one day (Nov 14, 2026) with Claude Code, right after [@ClaudeDevs announced theme mods](https://x.com/ClaudeDevs/status/2121392666244186327).

## Install

1. Clone this repo somewhere, for example `~/.claude/mods/code-and-cosmos`.
2. Add the folder to the `env` block in `~/.claude/settings.json`:
   ```json
   { "env": { "CLAUDE_CODE_PLUGIN_DIRS": "~/.claude/mods/code-and-cosmos" } }
   ```
3. Restart the desktop app, then run `/look space` or `/look rain`.

Theme mods work in local sessions only for now.

## The part nobody tells you: the app's limits

Whether an animated background plays smoothly or freezes into a still picture depends on rules in the app. I found them by reading the app's own code (Nov 14, 2026), and the app loads that code from the web, so these can change without an update:

- **A scene is one SVG of at most 131,072 characters**, with no script and nothing loaded from outside. The space scene here is 129,310 characters, which leaves 1,762 to spare.
- **One failed check freezes the whole scene.** A single `@media` rule about size, for example, means you get a still frame instead of motion. `scene_problems()` in `tools/build_scenes.py` runs that check before anything is written.
- **The app samples the scene on a 64 by 40 canvas every frame.** If a sample averages over about 5.5 ms across 3 seconds, the motion stops for good.
- **Flashes freeze it too.** If a quarter of any 341 by 256 pixel block swings between light and dark four times in a second, the still frame comes back for good.
- **So no filters on anything that moves.** A blur or noise filter on moving content costs too much, because the whole backdrop is redrawn every frame.
- **Thin filled shapes flicker on that tiny canvas.** Everything that moves in the black hole's disk is a stroke 22 units wide or less, never a thin fill.
- **People who turn off motion get the still frame,** so the still frame has to look right on its own.

## How it's built

The scenes are generated, not edited by hand:

```
python3 tools/rain.py     # writes hooks/rain-scene.js
python3 tools/space.py    # writes hooks/space-scene.js
```

To change a look, edit its generator and run it again. `hooks/register.tsx` wires up the `/look` command. `hooks/make-colors.js` is the color helper from Anthropic's theme examples, included unchanged as those examples instruct.

About 1,800 lines of Python and TypeScript in total.

## License

MIT. Made by Steve at [Swaymak](https://swaymak.ai), [@SwaymaKdotAI](https://x.com/SwaymaKdotAI).
