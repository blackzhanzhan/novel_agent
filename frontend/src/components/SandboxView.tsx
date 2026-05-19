import React, { useCallback, useEffect, useMemo, useRef } from 'react';
import { DiffEditor } from '@monaco-editor/react';
import { useUiCopy } from '../i18n/ui';

const CODE_REVIEW_DIFF_THEME = 'novel-agent-code-review-diff-dark';

interface SandboxViewProps {
    original: string;
    modified: string;
    isVisible: boolean;
    splitView?: boolean;
}

function findFirstChangedLine(original: string, modified: string): number {
    const originalLines = original.split('\n');
    const modifiedLines = modified.split('\n');
    const maxLines = Math.max(originalLines.length, modifiedLines.length);
    for (let index = 0; index < maxLines; index += 1) {
        if ((originalLines[index] ?? '') !== (modifiedLines[index] ?? '')) {
            return index + 1;
        }
    }
    return 1;
}

function defineCodeReviewDiffTheme(monaco: any) {
    monaco.editor.defineTheme(CODE_REVIEW_DIFF_THEME, {
        base: 'vs-dark',
        inherit: true,
        rules: [],
        colors: {
            'editor.background': '#090d13',
            'editorGutter.background': '#0b0f14',
            'editorLineNumber.foreground': '#7d8590',
            'editorLineNumber.activeForeground': '#c9d1d9',
            'diffEditor.insertedLineBackground': '#2ea04352',
            'diffEditor.removedLineBackground': '#f8514952',
            'diffEditor.insertedTextBackground': '#3fb95080',
            'diffEditor.removedTextBackground': '#f851497a',
            'diffEditor.insertedTextBorder': '#56d36480',
            'diffEditor.removedTextBorder': '#ff818280',
            'diffEditorGutter.insertedLineBackground': '#23863685',
            'diffEditorGutter.removedLineBackground': '#da363385',
            'diffEditorOverview.insertedForeground': '#3fb950',
            'diffEditorOverview.removedForeground': '#f85149',
            'editorGutter.addedBackground': '#3fb950',
            'editorGutter.deletedBackground': '#f85149',
            'editorGutter.modifiedBackground': '#d29922',
        },
    });
}

export const SandboxView: React.FC<SandboxViewProps> = ({ original, modified, isVisible, splitView = false }) => {
    const copy = useUiCopy();
    const diffEditorRef = useRef<any>(null);
    const diffUpdateDisposableRef = useRef<{ dispose?: () => void } | null>(null);
    const firstChangedLine = useMemo(() => findFirstChangedLine(original, modified), [modified, original]);

    const revealFirstChange = useCallback(() => {
        const editor = diffEditorRef.current;
        if (!editor) return;
        const reveal = () => {
            const modifiedLine = Math.max(1, firstChangedLine);
            const originalLine = Math.max(1, firstChangedLine);
            const modifiedEditor = editor.getModifiedEditor?.();
            const originalEditor = editor.getOriginalEditor?.();
            editor.layout?.();
            modifiedEditor?.layout?.();
            originalEditor?.layout?.();
            modifiedEditor?.setPosition?.({ lineNumber: modifiedLine, column: 1 });
            modifiedEditor?.revealLineInCenter?.(modifiedLine);
            originalEditor?.setPosition?.({ lineNumber: originalLine, column: 1 });
            originalEditor?.revealLineInCenter?.(originalLine);
        };
        [80, 300, 900, 1800, 3000].forEach((delay) => {
            window.setTimeout(reveal, delay);
        });
    }, [firstChangedLine]);

    useEffect(() => {
        if (!isVisible) return;
        revealFirstChange();
    }, [isVisible, revealFirstChange, splitView]);

    useEffect(() => {
        return () => {
            diffUpdateDisposableRef.current?.dispose?.();
        };
    }, []);

    if (!isVisible) {
        return (
            <div className="flex h-full w-full flex-1 flex-col items-center justify-center bg-[rgba(9,11,15,0.72)] p-8 text-center text-[var(--color-dark-text-muted)]">
                <div className="mb-4 rounded-[8px] border border-[rgba(255,255,255,0.05)] bg-[rgba(255,255,255,0.012)] px-3 py-1.5 text-[11px] font-mono text-[var(--color-dark-text-faint)]">
                    {copy.git.diffIdle}
                </div>
                <div className="mb-2 text-lg font-medium text-[var(--color-dark-text-main)]">{copy.git.noActiveDiff}</div>
                <div className="max-w-xs text-sm text-[var(--color-dark-text-faint)]">{copy.git.noActiveDiffHint}</div>
            </div>
        );
    }

    return (
        <div className="code-review-diff-shell flex-1 w-full h-full bg-[rgba(9,11,15,0.72)]">
            <DiffEditor
                height="100%"
                original={original}
                modified={modified}
                language="markdown"
                theme={CODE_REVIEW_DIFF_THEME}
                options={{
                    readOnly: true,
                    minimap: { enabled: false },
                    renderSideBySide: splitView,
                    wordWrap: 'on',
                    scrollBeyondLastLine: false,
                    fontSize: 13,
                    lineHeight: 21,
                    renderIndicators: true,
                    renderMarginRevertIcon: true,
                }}
                beforeMount={defineCodeReviewDiffTheme}
                onMount={(editor) => {
                    diffEditorRef.current = editor;
                    diffUpdateDisposableRef.current?.dispose?.();
                    diffUpdateDisposableRef.current = editor.onDidUpdateDiff?.(revealFirstChange) ?? null;
                    revealFirstChange();
                }}
                loading={<div className="p-4 text-[var(--color-dark-text-muted)]">{copy.git.loadingDiff}</div>}
            />
        </div>
    );
};
