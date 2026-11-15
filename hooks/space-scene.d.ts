import type { ThemeBackdropGlass } from 'claude-code'
import type { makeColors } from './make-colors.js'

/** The scene SVG the desktop app plays. Must pass tools/build_scenes.py scene_problems(). */
export const DEEP_SPACE: string
/** Extra CSS appended to the scene's <style> for phones only (size @media is allowed there). */
export const DEEP_SPACE_PORTRAIT: string
/** The look's colors: makeColors' definition; register.tsx adds only: 'dark'. */
export const SPACE_COLORS: Omit<Parameters<typeof makeColors>[0], 'only'>
/** How the app frosts its panels over the scene. */
export const SPACE_GLASS: ThemeBackdropGlass
/** What the scene shows, for a reader that cannot see it. */
export const SPACE_ALT: string
