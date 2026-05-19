export type ChapterLengthStatus = 'ok' | 'under_min' | 'over_max';

export interface ChapterLengthItem {
    title: string;
    nonWhitespaceChars: number;
    cjkChars: number;
    minChars: number;
    targetChars: number;
    maxChars: number;
    deficitToMin: number;
    deficitToTarget: number;
    status: ChapterLengthStatus;
}

export interface ChapterLengthReport {
    ok: boolean;
    chapterCount: number;
    underMinCount: number;
    overMaxCount: number;
    minChars: number;
    targetChars: number;
    maxChars: number;
    chapters: ChapterLengthItem[];
}

interface ChapterSpan {
    title: string;
    start: number;
    end: number;
}

const CHAPTER_HEADING_RE = /^(?:#{1,6}\s*)?(第[0-9０-９]+章[^\n\r]*)\s*$/;
const CJK_RE = /[\u3400-\u9fff\uf900-\ufaff]/g;

function splitChapterSpans(markdown: string): ChapterSpan[] {
    const lines = markdown.split(/\r?\n/);
    const starts: Array<{ title: string; line: number }> = [];
    let inFence = false;

    lines.forEach((line, index) => {
        if (/^\s*```/.test(line)) {
            inFence = !inFence;
            return;
        }
        if (inFence) return;
        const match = line.trim().match(CHAPTER_HEADING_RE);
        if (match) {
            starts.push({ title: match[1].trim(), line: index });
        }
    });

    return starts.map((start, index) => ({
        title: start.title,
        start: start.line + 1,
        end: index + 1 < starts.length ? starts[index + 1].line : lines.length,
    }));
}

function countTextUnits(text: string): { nonWhitespaceChars: number; cjkChars: number } {
    return {
        nonWhitespaceChars: text.replace(/\s/g, '').length,
        cjkChars: (text.match(CJK_RE) || []).length,
    };
}

export function measureChapterLengths(
    markdown: string,
    minChars = 2200,
    targetChars = 2500,
    maxChars = 3200,
): ChapterLengthReport {
    const lines = markdown.split(/\r?\n/);
    const chapters = splitChapterSpans(markdown).map((span) => {
        const body = lines.slice(span.start, span.end).join('\n');
        const counts = countTextUnits(body);
        const status: ChapterLengthStatus = counts.nonWhitespaceChars < minChars
            ? 'under_min'
            : counts.nonWhitespaceChars > maxChars
                ? 'over_max'
                : 'ok';

        return {
            title: span.title,
            nonWhitespaceChars: counts.nonWhitespaceChars,
            cjkChars: counts.cjkChars,
            minChars,
            targetChars,
            maxChars,
            deficitToMin: Math.max(0, minChars - counts.nonWhitespaceChars),
            deficitToTarget: Math.max(0, targetChars - counts.nonWhitespaceChars),
            status,
        };
    });

    const underMinCount = chapters.filter((chapter) => chapter.status === 'under_min').length;
    const overMaxCount = chapters.filter((chapter) => chapter.status === 'over_max').length;

    return {
        ok: underMinCount === 0,
        chapterCount: chapters.length,
        underMinCount,
        overMaxCount,
        minChars,
        targetChars,
        maxChars,
        chapters,
    };
}
