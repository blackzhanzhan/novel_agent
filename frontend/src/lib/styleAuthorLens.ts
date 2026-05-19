export const STYLE_AUTHOR_FILES = new Set([
    'style_fingerprint.md',
    'style_review.md',
    'style_constraints_for_continuation.md',
]);

export type StyleSectionTone = 'neutral' | 'accent' | 'warning';

export interface StyleMetricSnapshot {
    label?: string;
    chars?: number;
    paragraphs?: number;
    avgSentence?: number;
    avgPara?: number;
    dialogueRatio?: number;
    interiorDensity?: number;
    actionDensity?: number;
    environmentDensity?: number;
    expositionDensity?: number;
    suspenseDensity?: number;
}

export interface StyleMetricBadge {
    label: string;
    value: string;
    note: string;
}

export interface StyleAuthorSection {
    title: string;
    items: string[];
    tone: StyleSectionTone;
}

export interface StyleAuthorLens {
    eyebrow: string;
    title: string;
    sourceLabel: string;
    voiceSummary: string;
    sections: StyleAuthorSection[];
    evidenceTitle: string;
    evidenceItems: string[];
    metricBadges: StyleMetricBadge[];
    rawReportLabel: string;
}

function normalizeFileName(fileName: string): string {
    return String(fileName || '').replace(/\\/g, '/').split('/').pop()?.toLowerCase() || '';
}

export function isStyleAuthorFile(fileName?: string): boolean {
    return STYLE_AUTHOR_FILES.has(normalizeFileName(fileName || ''));
}

function asNumber(value: unknown): number | undefined {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value !== 'string') return undefined;
    const parsed = Number(value.replace('%', '').trim());
    if (!Number.isFinite(parsed)) return undefined;
    return value.includes('%') ? parsed / 100 : parsed;
}

function readJsonSnapshot(content: string): StyleMetricSnapshot {
    const match = content.match(/```json\s*([\s\S]*?)```/i);
    if (!match) return {};
    try {
        const parsed = JSON.parse(match[1]);
        const row = Array.isArray(parsed) ? parsed[0] : parsed;
        if (!row || typeof row !== 'object') return {};
        return {
            label: typeof row.label === 'string' ? row.label : undefined,
            chars: asNumber(row.chars),
            paragraphs: asNumber(row.paragraphs),
            avgSentence: asNumber(row.avg_sentence),
            avgPara: asNumber(row.avg_para),
            dialogueRatio: asNumber(row.dialogue_ratio),
            interiorDensity: asNumber(row.interior_density),
            actionDensity: asNumber(row.action_density),
            environmentDensity: asNumber(row.environment_density),
            expositionDensity: asNumber(row.exposition_density),
            suspenseDensity: asNumber(row.suspense_density),
        };
    } catch {
        return {};
    }
}

function readMetricLine(content: string, label: string, percent = false): number | undefined {
    const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const match = content.match(new RegExp(`${escaped}[：:]\\s*([0-9.]+%?)`));
    if (!match) return undefined;
    const raw = match[1];
    const parsed = Number(raw.replace('%', ''));
    if (!Number.isFinite(parsed)) return undefined;
    if (raw.includes('%')) return parsed / 100;
    if (percent && parsed > 1) return parsed / 100;
    return parsed;
}

function readMetrics(content: string): StyleMetricSnapshot {
    const jsonMetrics = readJsonSnapshot(content);
    return {
        label: jsonMetrics.label,
        chars: jsonMetrics.chars,
        paragraphs: jsonMetrics.paragraphs,
        avgSentence: jsonMetrics.avgSentence ?? readMetricLine(content, '句式呼吸'),
        avgPara: jsonMetrics.avgPara ?? readMetricLine(content, '段落节拍'),
        dialogueRatio: jsonMetrics.dialogueRatio ?? readMetricLine(content, '对白推进度', true),
        interiorDensity: jsonMetrics.interiorDensity ?? readMetricLine(content, '内心贴近度'),
        actionDensity: jsonMetrics.actionDensity ?? readMetricLine(content, '动作驱动度'),
        environmentDensity: jsonMetrics.environmentDensity ?? readMetricLine(content, '环境压迫感'),
        expositionDensity: jsonMetrics.expositionDensity ?? readMetricLine(content, '设定解释度'),
        suspenseDensity: jsonMetrics.suspenseDensity ?? readMetricLine(content, '悬念留白度'),
    };
}

function hasMetricBaseline(metrics: StyleMetricSnapshot): boolean {
    return metrics.avgSentence !== undefined || metrics.avgPara !== undefined || metrics.dialogueRatio !== undefined;
}

function formatNumber(value: number | undefined, suffix = ''): string {
    if (value === undefined) return '未记录';
    return `${Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1)}${suffix}`;
}

function formatPercent(value: number | undefined): string {
    if (value === undefined) return '未记录';
    return `${Math.round(value * 100)}%`;
}

function sentenceNote(value?: number): string {
    if (value === undefined) return '句长缺少基准';
    if (value < 20) return '短句快切';
    if (value < 25) return '偏快推进';
    if (value <= 32) return '中长句承压';
    return '长句铺陈';
}

function paragraphNote(value?: number): string {
    if (value === undefined) return '段落缺少基准';
    if (value < 32) return '换气很勤';
    if (value <= 48) return '短段推进';
    if (value <= 80) return '中段承载';
    return '段落偏重';
}

function dialogueNote(value?: number): string {
    if (value === undefined) return '对白缺少基准';
    if (value < 0.18) return '对白克制';
    if (value <= 0.3) return '对白点到即止';
    return '对白承担推进';
}

function densityNote(value: number | undefined, low: string, mid: string, high: string): string {
    if (value === undefined) return '缺少基准';
    if (value < 4) return low;
    if (value < 8) return mid;
    return high;
}

function stripMarkdown(line: string): string {
    return line
        .replace(/^\s*[-*]\s+/, '')
        .replace(/`+/g, '')
        .replace(/\*\*/g, '')
        .trim();
}

function uniqueItems(items: string[]): string[] {
    const seen = new Set<string>();
    const result: string[] = [];
    for (const raw of items) {
        const item = stripMarkdown(raw);
        if (!item || seen.has(item)) continue;
        seen.add(item);
        result.push(item);
    }
    return result;
}

function extractBulletsUnderHeading(content: string, heading: string): string[] {
    const lines = content.split(/\r?\n/);
    const startIndex = lines.findIndex((line) => line.trim() === `## ${heading}`);
    if (startIndex < 0) return [];
    const result: string[] = [];
    for (const line of lines.slice(startIndex + 1)) {
        if (/^#{1,3}\s+/.test(line)) break;
        if (/^\s*[-*]\s+/.test(line)) {
            result.push(stripMarkdown(line));
        }
    }
    return uniqueItems(result);
}

function extractParagraphsUnderHeading(content: string, heading: string): string[] {
    const lines = content.split(/\r?\n/);
    const startIndex = lines.findIndex((line) => line.trim() === `## ${heading}`);
    if (startIndex < 0) return [];
    const result: string[] = [];
    for (const line of lines.slice(startIndex + 1)) {
        if (/^#{1,3}\s+/.test(line)) break;
        const trimmed = stripMarkdown(line);
        if (!trimmed || trimmed === '```json' || trimmed === '```' || /^[{}"]/.test(trimmed)) continue;
        result.push(trimmed);
    }
    return uniqueItems(result);
}

function extractFirstMatch(content: string, patterns: RegExp[]): string | null {
    for (const pattern of patterns) {
        const match = content.match(pattern);
        if (match?.[1]) return stripMarkdown(match[1]);
    }
    return null;
}

function buildMetricBadges(metrics: StyleMetricSnapshot): StyleMetricBadge[] {
    return [
        { label: '句式', value: formatNumber(metrics.avgSentence, ' 字/句'), note: sentenceNote(metrics.avgSentence) },
        { label: '段落', value: formatNumber(metrics.avgPara, ' 字/段'), note: paragraphNote(metrics.avgPara) },
        { label: '对白', value: formatPercent(metrics.dialogueRatio), note: dialogueNote(metrics.dialogueRatio) },
        {
            label: '动作',
            value: formatNumber(metrics.actionDensity, '/千字'),
            note: densityNote(metrics.actionDensity, '动作很少', '动作参与推进', '动作驱动强'),
        },
        {
            label: '环境',
            value: formatNumber(metrics.environmentDensity, '/千字'),
            note: densityNote(metrics.environmentDensity, '环境轻', '环境承压', '环境压迫强'),
        },
        {
            label: '解释',
            value: formatNumber(metrics.expositionDensity, '/千字'),
            note: densityNote(metrics.expositionDensity, '解释很少', '解释适中', '解释偏密'),
        },
        {
            label: '留白',
            value: formatNumber(metrics.suspenseDensity, '/千字'),
            note: densityNote(metrics.suspenseDensity, '留白少', '留白稳定', '悬念密'),
        },
    ];
}

function metricSentence(metrics: StyleMetricSnapshot): string {
    if (!hasMetricBaseline(metrics)) {
        return '当前文件还没有可读数值基准，先阅读原始 Markdown 内容。';
    }
    const action = metrics.actionDensity ?? 0;
    const environment = metrics.environmentDensity ?? 0;
    const exposition = metrics.expositionDensity ?? 0;
    const driver = action >= environment && action >= exposition
        ? '人物行动和局势反应'
        : environment >= exposition
            ? '空间压力和现场气氛'
            : '设定解释和逻辑补足';
    return `${sentenceNote(metrics.avgSentence)}，${paragraphNote(metrics.avgPara)}；${dialogueNote(metrics.dialogueRatio)}，推进重心更靠${driver}。`;
}

function buildEvidence(content: string, fileName: string, metrics: StyleMetricSnapshot): string[] {
    const sample = extractFirstMatch(content, [
        /原文采样[：:]\s*([^\n]+)/,
        /对照样本[：:]\s*([^\n]+)/,
        /样本标签[：:]\s*([^\n]+)/,
    ]);
    const chapters = extractFirstMatch(content, [/原文章节[：:]\s*([^\n]+)/]);
    const evidence = [`当前文件：${normalizeFileName(fileName) || 'style artifact'}`];
    if (sample) evidence.push(sample);
    if (metrics.chars && metrics.paragraphs) {
        evidence.push(`样本规模：${metrics.chars} 字 / ${metrics.paragraphs} 段`);
    }
    if (chapters) evidence.push(`章节依据：${chapters}`);
    return evidence.slice(0, 4);
}

function buildFingerprintLens(content: string, fileName: string, metrics: StyleMetricSnapshot): StyleAuthorLens {
    const structure = [
        `句式：${formatNumber(metrics.avgSentence, ' 字/句')}，${sentenceNote(metrics.avgSentence)}。`,
        `段落：${formatNumber(metrics.avgPara, ' 字/段')}，${paragraphNote(metrics.avgPara)}。`,
        `对白：${formatPercent(metrics.dialogueRatio)}，${dialogueNote(metrics.dialogueRatio)}。`,
        `动作 / 环境 / 解释：${formatNumber(metrics.actionDensity, '/千字')}、${formatNumber(metrics.environmentDensity, '/千字')}、${formatNumber(metrics.expositionDensity, '/千字')}。`,
    ];
    return {
        eyebrow: '文风指纹',
        title: '原文近段结构',
        sourceLabel: metrics.label || normalizeFileName(fileName),
        voiceSummary: `这页只回答“原文最近怎么写”。${metricSentence(metrics)}`,
        sections: [
            { title: '读到的结构', items: structure, tone: 'accent' },
            {
                title: '适合怎么用',
                items: [
                    '给续写 Agent 做模仿参考，不直接判定草稿通过或失败。',
                    '当新轮回、新地图、新阶段切换时，重新生成它来刷新近段手感。',
                    '作者想改风格时，可以把这里当作“AI 当前读到的原文样本”。',
                ],
                tone: 'neutral',
            },
        ],
        evidenceTitle: '采样依据',
        evidenceItems: buildEvidence(content, fileName, metrics),
        metricBadges: buildMetricBadges(metrics),
        rawReportLabel: '指纹原文',
    };
}

function buildReviewLens(content: string, fileName: string, metrics: StyleMetricSnapshot): StyleAuthorLens {
    const conclusions = extractParagraphsUnderHeading(content, '审查结论');
    return {
        eyebrow: '文风审查',
        title: '最近文风偏差',
        sourceLabel: metrics.label || normalizeFileName(fileName),
        voiceSummary: '这页看“草稿相对原文有没有偏”。它是作者修改提示，不是卡死 demo 的硬闸门。',
        sections: [
            {
                title: '审查结论',
                items: conclusions.length > 0 ? conclusions : ['当前没有明确偏差结论，先以原始报告为准。'],
                tone: 'warning',
            },
            {
                title: '修改抓手',
                items: [
                    '只修影响阅读手感的偏差，剧情事实、胜负结果和人物动机不在这里改。',
                    '如果只是轻微风格差异，交给作者判断，不自动推倒重写。',
                    '需要重跑时先生成新基准，再让续写 Agent 自己参考原文和提示词模仿。',
                ],
                tone: 'neutral',
            },
        ],
        evidenceTitle: '审查依据',
        evidenceItems: buildEvidence(content, fileName, metrics),
        metricBadges: buildMetricBadges(metrics),
        rawReportLabel: '审查原文',
    };
}

function buildContinuationLens(content: string, fileName: string, metrics: StyleMetricSnapshot): StyleAuthorLens {
    const hardRules = extractBulletsUnderHeading(content, '写作硬约束');
    const boundaries = extractBulletsUnderHeading(content, '数值边界');
    return {
        eyebrow: '续写提示',
        title: '下一章文风抓手',
        sourceLabel: metrics.label || normalizeFileName(fileName),
        voiceSummary: `这页给 continuation Agent 当提示，不替作者决定文风优劣。${metricSentence(metrics)}`,
        sections: [
            {
                title: '续写抓手',
                items: hardRules.length > 0 ? hardRules.slice(0, 5) : [
                    '先写人物选择、动作反应和代价，再补必要解释。',
                    '对白只承担关键冲突或信息转折，避免连续问答顶替场景推进。',
                    '段落换气服务推进，不为了贴指标机械拆分。',
                ],
                tone: 'accent',
            },
            {
                title: '容易跑偏',
                items: boundaries.length > 0 ? boundaries.slice(0, 4) : [
                    '解释脱离人物动作时，会变成设定说明书。',
                    '对白连续问答时，会削弱现场推进感。',
                    '段落过碎时，行动链会失去连续压迫。',
                ],
                tone: 'warning',
            },
        ],
        evidenceTitle: '提示依据',
        evidenceItems: buildEvidence(content, fileName, metrics),
        metricBadges: buildMetricBadges(metrics),
        rawReportLabel: '提示原文',
    };
}

export function buildStyleAuthorLens(fileName: string, content: string): StyleAuthorLens {
    const metrics = readMetrics(content);
    const normalized = normalizeFileName(fileName);
    if (normalized === 'style_review.md') {
        return buildReviewLens(content, fileName, metrics);
    }
    if (normalized === 'style_constraints_for_continuation.md') {
        return buildContinuationLens(content, fileName, metrics);
    }
    return buildFingerprintLens(content, fileName, metrics);
}
