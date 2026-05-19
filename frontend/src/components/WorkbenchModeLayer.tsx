import React from 'react';
import { WorkbenchMode } from '../types/store';

interface WorkbenchModeLayerProps {
    activeMode: WorkbenchMode;
    editorView: React.ReactNode;
    reviewView: React.ReactNode;
    gitView: React.ReactNode;
}

function layerClass(isActive: boolean, offsetClass: string): string {
    return `absolute inset-0 flex min-h-0 min-w-0 flex-col overflow-hidden transition-all duration-200 ease-out ${
        isActive
            ? 'pointer-events-auto translate-x-0 opacity-100'
            : `pointer-events-none ${offsetClass} opacity-0`
    }`;
}

export const WorkbenchModeLayer: React.FC<WorkbenchModeLayerProps> = ({
    activeMode,
    editorView,
    reviewView,
    gitView,
}) => {
    const editorActive = activeMode === 'editor';
    const reviewActive = activeMode === 'review';
    const gitActive = activeMode === 'git';

    return (
        <div className="relative h-full min-h-0 w-full overflow-hidden">
            <section
                inert={!editorActive}
                aria-hidden={!editorActive}
                className={layerClass(editorActive, '-translate-x-2')}
            >
                {editorView}
            </section>
            <section
                inert={!reviewActive}
                aria-hidden={!reviewActive}
                className={layerClass(reviewActive, 'translate-y-2')}
            >
                {reviewView}
            </section>
            <section
                inert={!gitActive}
                aria-hidden={!gitActive}
                className={layerClass(gitActive, 'translate-x-2')}
            >
                {gitView}
            </section>
        </div>
    );
};
