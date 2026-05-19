import React from 'react';
import { Group, Panel, Separator, useDefaultLayout } from 'react-resizable-panels';

interface AppLayoutProps {
    leftPanel: React.ReactNode;
    centerPanel: React.ReactNode;
    rightPanel: React.ReactNode;
    activityBar?: React.ReactNode;
    topBar?: React.ReactNode;
}

function ResizeHandle() {
    return (
        <Separator
            className="group relative w-3 shrink-0 cursor-col-resize bg-transparent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-accent-blue)]"
        >
            <div className="absolute inset-y-4 left-1/2 w-px -translate-x-1/2 rounded-full bg-[rgba(255,255,255,0.05)] transition-all duration-150 group-hover:inset-y-3 group-hover:bg-[rgba(255,255,255,0.2)]" />
            <div className="absolute inset-y-[28%] left-1/2 hidden w-[3px] -translate-x-1/2 rounded-full bg-[rgba(255,255,255,0.14)] blur-[1px] transition-opacity duration-150 group-hover:block" />
        </Separator>
    );
}

export const AppLayout: React.FC<AppLayoutProps> = ({
    leftPanel,
    centerPanel,
    rightPanel,
    activityBar,
    topBar,
}) => {
    const layout = useDefaultLayout({
        id: 'loregit-workbench-layout-v4',
        panelIds: ['left', 'center', 'right'],
    });

    return (
        <div className="cursor-shell flex h-screen w-screen flex-col overflow-hidden text-[var(--color-dark-text-main)]">
            <div className="pointer-events-none absolute inset-0 overflow-hidden">
                <div className="absolute left-[18%] top-0 h-[38vh] w-[42vw] rounded-full bg-[radial-gradient(circle,rgba(255,255,255,0.06)_0%,rgba(255,255,255,0)_72%)] opacity-55 blur-3xl" />
                <div className="absolute bottom-[-18vh] right-[14%] h-[46vh] w-[34vw] rounded-full bg-[radial-gradient(circle,rgba(255,255,255,0.035)_0%,rgba(255,255,255,0)_74%)] opacity-70 blur-3xl" />
            </div>
            {topBar && (
                <div className="cursor-topbar z-20 mx-2 mt-2 flex h-[52px] items-center rounded-[12px] border px-4">
                    {topBar}
                </div>
            )}
            <div className="min-h-0 flex-1 overflow-hidden">
                <div className="flex h-full w-full gap-2 bg-transparent px-2 pb-2 pt-2">
                    {activityBar ? (
                        <div className="cursor-panel cursor-panel-subtle flex h-full w-[58px] shrink-0 overflow-hidden rounded-[16px] border">
                            {activityBar}
                        </div>
                    ) : null}
                    <Group
                        orientation="horizontal"
                        defaultLayout={layout.defaultLayout}
                        onLayoutChanged={layout.onLayoutChanged}
                        className="h-full min-w-0 flex-1 gap-0"
                    >
                        <Panel id="left" defaultSize="15%" minSize="11%" maxSize="26%">
                            <div data-shot="left-rail" className="cursor-panel cursor-panel-subtle flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-[16px] border">
                                {leftPanel}
                            </div>
                        </Panel>
                        <ResizeHandle />

                        <Panel id="center" defaultSize="52%" minSize="20%">
                            <div data-shot="center-surface" className="cursor-panel-elevated cursor-center-panel flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-[18px] border">
                                {centerPanel}
                            </div>
                        </Panel>

                        <ResizeHandle />
                        <Panel id="right" defaultSize="33%" minSize="20%" maxSize="52%">
                            <div data-shot="right-rail" className="cursor-panel cursor-side-panel flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-[16px] border">
                                {rightPanel}
                            </div>
                        </Panel>
                    </Group>
                </div>
            </div>
        </div>
    );
};
