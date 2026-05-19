# Frontend Theme Options

## Context

This workbench is no longer using a single ad-hoc dark palette.

We now maintain three theme presets and apply one as the current default.

The presets are defined in:

- `frontend/src/lib/themePresets.ts`
- `frontend/src/index.css`

## 1. OpenCode Noir

- ID: `opencode-noir`
- Position: **current default**

### Character
- black / white / gray first
- lowest saturation
- closest to the restrained desktop-IDE feel we want right now

### Strengths
- keeps the chat body and editor body visually dominant
- makes the conversation selector behave more like history/navigation
- best fit for our current “serious workbench” direction

### Weaknesses
- can feel severe or cold if the information density becomes too high

## 2. Graphite Fog

- ID: `graphite-fog`

### Character
- colder graphite layers
- softer panel transitions
- more “technical” than “editorial”

### Strengths
- very clean for dense multi-panel layouts
- better if we later want stronger code-tool vibes

### Weaknesses
- easier to drift back toward “generic dark devtool”
- less distinctive for a writing-focused workbench

## 3. Ink Stone

- ID: `ink-stone`

### Character
- warm dark neutrals
- slightly more human / literary tone
- still restrained, but less clinical

### Strengths
- strong fit for long-form reading and writing
- makes markdown and prose areas feel warmer

### Weaknesses
- if overused, can reduce the sharpness of operational states

## Why `OpenCode Noir` is the current default

We chose `OpenCode Noir` as the default because:

1. it best supports the current UI goal:
   - conversation selector becomes secondary
   - chat/editor body becomes primary
2. it removes the leftover “blue/green SaaS control panel” feeling most decisively
3. it is the safest baseline for future right-rail and editor refinements

## Design Rule Going Forward

If we continue refining the UI:

- keep **structure** more important than color
- keep the **selector weak** and the **content strong**
- use color only for:
  - danger
  - warning
  - conflict
- avoid reintroducing blue or green as large-area focus colors
