export interface WorkbenchThemePreset {
    id: 'opencode-noir' | 'graphite-fog' | 'ink-stone';
    label: string;
    summary: string;
}

export const WORKBENCH_THEME_PRESETS: WorkbenchThemePreset[] = [
    {
        id: 'opencode-noir',
        label: 'OpenCode Noir',
        summary: '黑白灰主导，最克制、最接近你当前要的桌面 IDE 气质。',
    },
    {
        id: 'graphite-fog',
        label: 'Graphite Fog',
        summary: '更冷、更薄的石墨灰层级，适合强调连续工作面与轻分隔。',
    },
    {
        id: 'ink-stone',
        label: 'Ink Stone',
        summary: '偏暖的墨黑与石灰层级，适合更有人文感的写作工作台。',
    },
];

export const DEFAULT_WORKBENCH_THEME_ID: WorkbenchThemePreset['id'] = 'opencode-noir';
