# OpenCode Desktop UI Entry Map

This file is a reading map for the local sparse reference clone at:

- `reference_upstreams/opencode-desktop`

It is intentionally focused on the **desktop UI shell and interaction language**, not the CLI or extension surfaces.

## What We Verified

- Repo: `anomalyco/opencode`
- Branch: `dev`
- Reference scope currently checked out:
  - `packages/desktop`
  - `packages/desktop-electron`
  - `packages/app`
  - `packages/ui`

## Desktop Shell Entry Points

### 1. Tauri desktop shell
- `reference_upstreams/opencode-desktop/packages/desktop/src/index.tsx`
- `reference_upstreams/opencode-desktop/packages/desktop/src/entry.tsx`
- `reference_upstreams/opencode-desktop/packages/desktop/src/styles.css`

Why it matters:
- shows how the native desktop shell is bootstrapped
- shows desktop-specific glue such as window, deep-link, updater, storage, and shell integration
- `styles.css` reveals top-level app-shell motion and progress language

### 2. Electron desktop shell
- `reference_upstreams/opencode-desktop/packages/desktop-electron/src/renderer/index.tsx`
- `reference_upstreams/opencode-desktop/packages/desktop-electron/src/renderer/styles.css`
- `reference_upstreams/opencode-desktop/packages/desktop-electron/src/main/windows.ts`
- `reference_upstreams/opencode-desktop/packages/desktop-electron/src/main/index.ts`

Why it matters:
- gives the desktop renderer bootstrap for the Electron path
- helps separate actual desktop-window behavior from shared app UI

## Shared App Surface

### 3. Main app composition
- `reference_upstreams/opencode-desktop/packages/app/src/app.tsx`
- `reference_upstreams/opencode-desktop/packages/app/src/index.css`
- `reference_upstreams/opencode-desktop/packages/app/src/entry.tsx`

Why it matters:
- this is where the actual app-level layout, providers, routing, and shell composition live
- if we want to learn overall page hierarchy and workbench semantics, this is the highest-value entry

## Shared UI Language

### 4. Core component library
- `reference_upstreams/opencode-desktop/packages/ui/src/components/list.tsx`
- `reference_upstreams/opencode-desktop/packages/ui/src/components/list.css`
- `reference_upstreams/opencode-desktop/packages/ui/src/components/dock-prompt.tsx`
- `reference_upstreams/opencode-desktop/packages/ui/src/components/dock-surface.tsx`
- `reference_upstreams/opencode-desktop/packages/ui/src/components/message-nav.tsx`
- `reference_upstreams/opencode-desktop/packages/ui/src/components/message-part.tsx`
- `reference_upstreams/opencode-desktop/packages/ui/src/components/markdown.tsx`
- `reference_upstreams/opencode-desktop/packages/ui/src/components/inline-input.tsx`
- `reference_upstreams/opencode-desktop/packages/ui/src/components/icon-button.tsx`
- `reference_upstreams/opencode-desktop/packages/ui/src/components/card.tsx`
- `reference_upstreams/opencode-desktop/packages/ui/src/components/diff-changes.tsx`

Why it matters:
- `list.*` is the most relevant family for our conversation selector rethink
- `dock-prompt.*` and `dock-surface.*` are directly relevant to our input/composer redesign
- `message-nav.*` and `message-part.*` are relevant to chat history / thread rendering semantics
- `diff-changes.*` is relevant to how they treat review/diff surfaces without backend-card aesthetics

## Theme / Token Direction

### 5. Token and tailwind generation clues
- `reference_upstreams/opencode-desktop/packages/ui/script/tailwind.ts`
- `reference_upstreams/opencode-desktop/packages/ui/script/colors.txt`

Why it matters:
- helps infer their palette and utility generation approach
- useful for understanding how restrained their color and density system is

## Recommended Reading Order

1. `packages/app/src/app.tsx`
2. `packages/ui/src/components/list.tsx`
3. `packages/ui/src/components/dock-prompt.tsx`
4. `packages/ui/src/components/message-nav.tsx`
5. `packages/ui/src/components/message-part.tsx`
6. `packages/ui/src/components/diff-changes.tsx`
7. `packages/desktop/src/styles.css`
8. `packages/desktop-electron/src/renderer/styles.css`

## What To Learn For Our Workbench

### Most relevant lessons
- how to make a selector behave like a **history list**, not a card gallery
- how to make the input area feel like a **dock / command composer**
- how to keep the shell **continuous**, not split into obvious SaaS cards
- how to use **black/white/gray hierarchy** instead of colorful state blocks
- how to let the **current content** stay visually dominant over controls

## What Not To Copy Blindly

- native window APIs
- updater / deep-link / storage glue
- platform-specific shell code
- component names as if they were one-to-one with our React workbench

We should learn the **design language and information hierarchy**, not transplant the implementation directly.
