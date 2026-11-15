import type { CommandRunResult, EngineInterface, Register, ThemeSetArgs } from 'claude-code'

import { makeColors } from './make-colors.js'
import { CODE_RAIN, CODE_RAIN_PORTRAIT, RAIN_ALT, RAIN_COLORS, RAIN_GLASS } from './rain-scene.js'
import { DEEP_SPACE, DEEP_SPACE_PORTRAIT, SPACE_ALT, SPACE_COLORS, SPACE_GLASS } from './space-scene.js'

// Two night looks. Each is a dark color theme plus an animated scene behind
// the chat. Switch with /look rain, /look space or /look off.
// Each look's scene, colors, glass and description live in its own file,
// hooks/rain-scene.js and hooks/space-scene.js, written by tools/rain.py and
// tools/space.py. This file only wires them up.

const rain = makeColors({ ...RAIN_COLORS, only: 'dark' })
const space = makeColors({ ...SPACE_COLORS, only: 'dark' })

type LookName = 'rain' | 'space'

type Look = {
  title: string
  args: ThemeSetArgs
  problems: string[]
}

const LOOKS: Record<LookName, Look> = {
  rain: {
    title: 'Code rain',
    problems: rain.problems,
    args: {
      colors: rain.theme,
      overrideColorScheme: 'dark',
      backdrop: { scene: 'cc-code-rain', glass: RAIN_GLASS },
    },
  },
  space: {
    title: 'Deep space',
    problems: space.problems,
    args: {
      colors: space.theme,
      overrideColorScheme: 'dark',
      backdrop: { scene: 'cc-deep-space', glass: SPACE_GLASS },
    },
  },
}

// `portrait` is extra CSS that re-places things on a tall screen. It goes to
// phones alone: the desktop app only lets a scene move when its CSS asks no
// @media but prefers-reduced-motion and prefers-color-scheme, and draws a
// still frame otherwise. tools/build_scenes.py checks `source` against that.
const SCENES: Record<string, { source: string; portrait: string; alt: string }> = {
  'cc-code-rain': { source: CODE_RAIN, portrait: CODE_RAIN_PORTRAIT, alt: RAIN_ALT },
  'cc-deep-space': { source: DEEP_SPACE, portrait: DEEP_SPACE_PORTRAIT, alt: SPACE_ALT },
}

const ALIASES: Record<string, LookName | 'off'> = {
  rain: 'rain',
  code: 'rain',
  matrix: 'rain',
  space: 'space',
  universe: 'space',
  cosmos: 'space',
  stars: 'space',
  off: 'off',
  none: 'off',
}

const STORE_KEY = 'look'
const DEFAULT_LOOK: LookName = 'rain'

function isLookName(value: unknown): value is LookName {
  return value === 'rain' || value === 'space'
}

async function applyLook($: EngineInterface, name: LookName): Promise<string> {
  const look = LOOKS[name]
  const unpainted = look.problems.find(line => line.startsWith("Desktop won't paint"))

  if (unpainted !== undefined) {
    $.ui.toast(unpainted)
  }
  const result = await $.theme.set(look.args)

  if (!result.isDrawn) {
    return `${look.title} is set, but nothing here draws it yet: ${result.reason}`
  }
  $.ui.status(undefined)

  return `${look.title} is on.`
}

// /look answers with a brief pop-up and no text: a plugin command's text
// becomes a row in the chat and stays in what Claude reads.
function quietly($: EngineInterface, text: string): CommandRunResult {
  $.ui.toast(text)

  return {}
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'look',
      description: 'Switch the app look: /look rain, /look space, or /look off',
    })
    const saved = await $.store.get(STORE_KEY)

    if (saved !== 'off') {
      const message = await applyLook($, isLookName(saved) ? saved : DEFAULT_LOOK)

      if (!message.endsWith('is on.')) {
        $.ui.status(message)
      }
    }

    return next(e)
  })

  on('command.run', { command: 'look' }, async ($, e) => {
    const asked = e.args.trim().toLowerCase()
    const saved = await $.store.get(STORE_KEY)
    const current = saved === 'off' ? 'off' : isLookName(saved) ? saved : DEFAULT_LOOK

    if (asked === '') {
      const now = current === 'off' ? 'No look is on.' : `${LOOKS[current].title} is on.`

      return quietly($, `${now} Try /look rain, /look space, or /look off.`)
    }
    const choice = ALIASES[asked]

    if (choice === undefined) {
      return quietly($, `I don't know the look "${asked}". Try /look rain, /look space, or /look off.`)
    }
    await $.store.set(STORE_KEY, choice)

    if (choice === 'off') {
      await $.theme.clear()

      return quietly($, "Back to the app's own look. /look rain or /look space brings one back.")
    }

    return quietly($, await applyLook($, choice))
  })

  on('ui.render', { component: 'Backdrop' }, ($, e, next) => {
    const scene = SCENES[e.props.scene]

    if (scene === undefined || (e.surface !== 'desktop' && e.surface !== 'mobile')) {
      return next(e)
    }
    const { Svg } = $.ui.resolve(e)
    const source =
      e.surface === 'mobile' ? scene.source.replace('</style>', () => `${scene.portrait}</style>`) : scene.source

    return <Svg source={source} alt={scene.alt} isInteractive />
  })
}
