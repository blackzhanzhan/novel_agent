import type { ReactDiffViewerStylesOverride } from 'react-diff-viewer-continued';

export const codeReviewDiffStyles: ReactDiffViewerStylesOverride = {
    variables: {
        dark: {
            diffViewerBackground: '#090d13',
            diffViewerColor: '#e6edf3',
            diffViewerTitleBackground: '#0d1117',
            diffViewerTitleColor: '#c9d1d9',
            diffViewerTitleBorderColor: 'rgba(255,255,255,0.08)',
            addedBackground: 'rgba(46, 160, 67, 0.32)',
            addedColor: '#e6ffed',
            removedBackground: 'rgba(248, 81, 73, 0.32)',
            removedColor: '#ffeef0',
            changedBackground: 'rgba(210, 153, 34, 0.18)',
            wordAddedBackground: 'rgba(63, 185, 80, 0.5)',
            wordRemovedBackground: 'rgba(248, 81, 73, 0.48)',
            addedGutterBackground: 'rgba(35, 134, 54, 0.52)',
            removedGutterBackground: 'rgba(218, 54, 51, 0.52)',
            gutterBackground: '#0d1117',
            gutterBackgroundDark: '#0b0f14',
            gutterColor: '#7d8590',
            addedGutterColor: '#d7fbe1',
            removedGutterColor: '#ffd7d7',
            highlightBackground: 'rgba(210, 153, 34, 0.18)',
            highlightGutterBackground: 'rgba(210, 153, 34, 0.3)',
            codeFoldGutterBackground: '#111722',
            codeFoldBackground: '#101722',
            emptyLineBackground: '#10141b',
            codeFoldContentColor: '#8b949e',
        },
    },
    diffContainer: {
        borderRadius: 0,
        background: '#090d13',
        color: '#e6edf3',
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
        fontSize: '12px',
    },
    line: {
        minHeight: '22px',
        lineHeight: '22px',
        '&:hover': {
            background: 'rgba(255, 255, 255, 0.035)',
        },
    },
    diffAdded: {
        boxShadow: 'inset 3px 0 0 rgba(63, 185, 80, 0.86)',
    },
    diffRemoved: {
        boxShadow: 'inset 3px 0 0 rgba(248, 81, 73, 0.86)',
    },
    gutter: {
        borderRight: '1px solid rgba(255, 255, 255, 0.06)',
        minWidth: '44px',
    },
    lineNumber: {
        color: 'inherit',
        fontSize: '11px',
        minWidth: '34px',
    },
    marker: {
        color: 'inherit',
        fontWeight: 700,
        paddingRight: '8px',
    },
    contentText: {
        color: 'inherit',
    },
    wordAdded: {
        borderRadius: '3px',
        outline: '1px solid rgba(86, 211, 100, 0.32)',
        textDecoration: 'none',
    },
    wordRemoved: {
        borderRadius: '3px',
        outline: '1px solid rgba(255, 129, 130, 0.32)',
        textDecoration: 'none',
    },
    codeFold: {
        borderTop: '1px solid rgba(255, 255, 255, 0.05)',
        borderBottom: '1px solid rgba(255, 255, 255, 0.05)',
    },
};
