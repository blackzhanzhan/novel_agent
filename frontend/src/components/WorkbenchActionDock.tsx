import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FileType, FsmState, WorkbenchMode } from '../types/store';

export type WorkbenchActionStatus = 'available' | 'coming_soon' | 'external_panel' | 'disabled';
export type WorkbenchActionRunState = 'idle' | 'running' | 'success' | 'error';
export type WorkbenchActionExecutionKind = 'direct_job' | 'external_panel' | 'future_action';
export type WorkbenchActionProgressMode = 'none' | 'bar';

export interface WorkbenchActionProgress {
    mode: WorkbenchActionProgressMode;
    current: number;
    total: number;
    label?: string;
    lines?: string[];
}

export interface WorkbenchActionControl {
    id: string;
    label: string;
    description?: string;
    tone?: 'primary' | 'secondary';
    disabled?: boolean;
    onRun?: () => void;
}

export interface WorkbenchActionItem {
    id: string;
    label: string;
    description: string;
    guidance?: string[];
    executionKind: WorkbenchActionExecutionKind;
    requiresPrompt: boolean;
    status: WorkbenchActionStatus;
    runState?: WorkbenchActionRunState;
    meta?: string;
    progress?: WorkbenchActionProgress;
    controls?: WorkbenchActionControl[];
    onRun?: () => void;
}

interface WorkbenchActionDockProps {
    activeFile: string;
    activeFileType: FileType;
    fsmState: FsmState;
    workbenchMode: WorkbenchMode;
    repoNeedsRepair: boolean;
    actions: WorkbenchActionItem[];
}

interface DockPosition {
    left: number;
    top: number;
}

interface DragState {
    pointerId: number;
    originX: number;
    originY: number;
    startLeft: number;
    startTop: number;
    moved: boolean;
    suppressClick: boolean;
    lastPosition?: DockPosition;
}

const DOCK_POSITION_STORAGE_KEY = 'novel-agent.workbench-action-dock.position';
const DOCK_MARGIN = 12;
const DEFAULT_DOCK_WIDTH = 320;
const DEFAULT_DOCK_CLOSED_HEIGHT = 44;
const DRAG_CLICK_THRESHOLD = 4;

function clampDockPosition(
    position: DockPosition,
    width = DEFAULT_DOCK_WIDTH,
    height = DEFAULT_DOCK_CLOSED_HEIGHT,
    minTop = DOCK_MARGIN,
): DockPosition {
    if (typeof window === 'undefined') return position;
    const maxLeft = Math.max(DOCK_MARGIN, window.innerWidth - width - DOCK_MARGIN);
    const maxTop = Math.max(DOCK_MARGIN, window.innerHeight - height - DOCK_MARGIN);
    return {
        left: Math.min(Math.max(DOCK_MARGIN, position.left), maxLeft),
        top: Math.min(Math.max(minTop, position.top), maxTop),
    };
}

function defaultDockPosition(): DockPosition {
    if (typeof window === 'undefined') return { left: 540, top: 720 };
    return clampDockPosition({
        left: window.innerWidth - DEFAULT_DOCK_WIDTH - 460,
        top: window.innerHeight - DEFAULT_DOCK_CLOSED_HEIGHT - 20,
    });
}

function readStoredDockPosition(): DockPosition {
    if (typeof window === 'undefined') return defaultDockPosition();
    try {
        const raw = window.localStorage.getItem(DOCK_POSITION_STORAGE_KEY);
        if (!raw) return defaultDockPosition();
        const parsed = JSON.parse(raw);
        if (
            typeof parsed?.left === 'number'
            && Number.isFinite(parsed.left)
            && typeof parsed?.top === 'number'
            && Number.isFinite(parsed.top)
        ) {
            return clampDockPosition({ left: parsed.left, top: parsed.top });
        }
    } catch {
        // Ignore malformed local UI preferences and fall back to the default dock position.
    }
    return defaultDockPosition();
}

function writeStoredDockPosition(position: DockPosition): void {
    if (typeof window === 'undefined') return;
    try {
        window.localStorage.setItem(DOCK_POSITION_STORAGE_KEY, JSON.stringify(position));
    } catch {
        // Local storage is a convenience only; dragging should still work without it.
    }
}

function statusLabel(status: WorkbenchActionStatus): string {
    if (status === 'available') return '可执行';
    if (status === 'external_panel') return '已有专区';
    if (status === 'disabled') return '不可用';
    return '预留';
}

function runStateLabel(runState?: WorkbenchActionRunState): string | null {
    if (runState === 'running') return '运行中';
    if (runState === 'success') return '完成';
    if (runState === 'error') return '失败';
    return null;
}

function actionControls(action: WorkbenchActionItem): WorkbenchActionControl[] {
    if (action.controls && action.controls.length > 0) return action.controls;
    if (action.onRun) {
        return [{ id: 'run', label: '执行', tone: 'primary', onRun: action.onRun }];
    }
    return [];
}

function isControlRunnable(control: WorkbenchActionControl): boolean {
    return !control.disabled && typeof control.onRun === 'function';
}

function isActionRunnable(action: WorkbenchActionItem): boolean {
    return action.status === 'available' && actionControls(action).some(isControlRunnable);
}

function progressPercent(progress?: WorkbenchActionProgress): number {
    if (!progress || progress.mode !== 'bar' || progress.total <= 0) return 0;
    return Math.max(0, Math.min(100, Math.round((progress.current / progress.total) * 100)));
}

export const WorkbenchActionDock: React.FC<WorkbenchActionDockProps> = ({
    activeFile,
    activeFileType,
    fsmState,
    workbenchMode,
    repoNeedsRepair,
    actions,
}) => {
    const [open, setOpen] = useState(false);
    const dockRef = useRef<HTMLDivElement | null>(null);
    const panelRef = useRef<HTMLDivElement | null>(null);
    const dragStateRef = useRef<DragState | null>(null);
    const suppressNextClickRef = useRef(false);
    const [position, setPosition] = useState<DockPosition>(() => readStoredDockPosition());
    const runnableCount = useMemo(() => actions.filter(isActionRunnable).length, [actions]);
    const visibleActions = actions;

    const clampWithCurrentSize = useCallback((nextPosition: DockPosition): DockPosition => {
        const rect = dockRef.current?.getBoundingClientRect();
        const panelRect = open ? panelRef.current?.getBoundingClientRect() : null;
        const minTop = panelRect ? DOCK_MARGIN + panelRect.height + 8 : DOCK_MARGIN;
        return clampDockPosition(
            nextPosition,
            rect?.width || DEFAULT_DOCK_WIDTH,
            DEFAULT_DOCK_CLOSED_HEIGHT,
            minTop,
        );
    }, [open]);

    const persistPosition = useCallback((nextPosition: DockPosition) => {
        const clamped = clampWithCurrentSize(nextPosition);
        setPosition(clamped);
        writeStoredDockPosition(clamped);
    }, [clampWithCurrentSize]);

    useEffect(() => {
        const handleResize = () => {
            setPosition((current) => {
                const clamped = clampWithCurrentSize(current);
                writeStoredDockPosition(clamped);
                return clamped;
            });
        };
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, [clampWithCurrentSize]);

    useEffect(() => {
        setPosition((current) => clampWithCurrentSize(current));
    }, [clampWithCurrentSize, open]);

    useEffect(() => {
        const updateDrag = (clientX: number, clientY: number) => {
            const dragState = dragStateRef.current;
            if (!dragState) return false;
            const deltaX = clientX - dragState.originX;
            const deltaY = clientY - dragState.originY;
            if (Math.abs(deltaX) > DRAG_CLICK_THRESHOLD || Math.abs(deltaY) > DRAG_CLICK_THRESHOLD) {
                dragState.moved = true;
                if (dragState.suppressClick) {
                    suppressNextClickRef.current = true;
                }
            }
            if (!dragState.moved) return false;
            const nextPosition = clampWithCurrentSize({
                left: dragState.startLeft + deltaX,
                top: dragState.startTop + deltaY,
            });
            dragState.lastPosition = nextPosition;
            setPosition(nextPosition);
            return true;
        };

        const finishDrag = (clientX: number, clientY: number) => {
            const dragState = dragStateRef.current;
            if (!dragState) return false;
            dragStateRef.current = null;
            if (!dragState.moved) return false;
            persistPosition(dragState.lastPosition || clampWithCurrentSize({
                left: dragState.startLeft + clientX - dragState.originX,
                top: dragState.startTop + clientY - dragState.originY,
            }));
            return true;
        };

        const handleMouseMove = (event: MouseEvent) => {
            if (updateDrag(event.clientX, event.clientY)) {
                event.preventDefault();
            }
        };
        const handleMouseUp = (event: MouseEvent) => {
            if (finishDrag(event.clientX, event.clientY)) {
                event.preventDefault();
            }
        };
        const handleTouchMove = (event: TouchEvent) => {
            const touch = event.touches[0];
            if (touch && updateDrag(touch.clientX, touch.clientY)) {
                event.preventDefault();
            }
        };
        const handleTouchEnd = (event: TouchEvent) => {
            const touch = event.changedTouches[0];
            if (touch && finishDrag(touch.clientX, touch.clientY)) {
                event.preventDefault();
            }
        };

        window.addEventListener('mousemove', handleMouseMove);
        window.addEventListener('mouseup', handleMouseUp);
        window.addEventListener('touchmove', handleTouchMove, { passive: false });
        window.addEventListener('touchend', handleTouchEnd);
        window.addEventListener('touchcancel', handleTouchEnd);
        return () => {
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseup', handleMouseUp);
            window.removeEventListener('touchmove', handleTouchMove);
            window.removeEventListener('touchend', handleTouchEnd);
            window.removeEventListener('touchcancel', handleTouchEnd);
        };
    }, [clampWithCurrentSize, persistPosition]);

    const startDrag = useCallback((clientX: number, clientY: number, suppressClick: boolean) => {
        dragStateRef.current = {
            pointerId: 0,
            originX: clientX,
            originY: clientY,
            startLeft: position.left,
            startTop: position.top,
            moved: false,
            suppressClick,
        };
    }, [position.left, position.top]);

    const handleDragMouseDown = useCallback((event: React.MouseEvent<HTMLElement>) => {
        if (event.button !== 0) return;
        const target = event.target as HTMLElement;
        if (target.closest('[data-workbench-action-control="true"]')) return;
        startDrag(event.clientX, event.clientY, event.currentTarget instanceof HTMLButtonElement);
        event.preventDefault();
    }, [startDrag]);

    const handleDragTouchStart = useCallback((event: React.TouchEvent<HTMLElement>) => {
        const target = event.target as HTMLElement;
        if (target.closest('[data-workbench-action-control="true"]')) return;
        const touch = event.touches[0];
        if (!touch) return;
        startDrag(touch.clientX, touch.clientY, event.currentTarget instanceof HTMLButtonElement);
    }, [startDrag]);

    const handleToggleClick = useCallback(() => {
        if (suppressNextClickRef.current) {
            suppressNextClickRef.current = false;
            return;
        }
        setOpen((value) => !value);
    }, []);

    return (
        <div
            ref={dockRef}
            data-workbench-action-dock="true"
            className="fixed z-40 w-[320px]"
            style={{ left: position.left, top: position.top }}
        >
            {open && (
                <div
                    ref={panelRef}
                    className="absolute bottom-[calc(100%+0.5rem)] right-0 w-[320px] overflow-hidden rounded-[14px] border border-[rgba(255,255,255,0.08)] bg-[rgba(13,16,22,0.96)] shadow-[0_20px_50px_rgba(0,0,0,0.38)] backdrop-blur"
                >
                    <div
                        className="touch-none cursor-move select-none border-b border-[rgba(255,255,255,0.06)] px-3 py-3"
                        onMouseDown={handleDragMouseDown}
                        onTouchStart={handleDragTouchStart}
                        title="拖动工作台动作"
                    >
                        <div className="flex items-center justify-between gap-2">
                            <div>
                                <div className="text-[11px] font-semibold text-[var(--color-dark-text-main)]">工作台动作</div>
                                <div className="mt-0.5 text-[9px] font-mono text-[var(--color-dark-text-faint)]">
                                    {activeFile} · {activeFileType} · {workbenchMode}
                                </div>
                            </div>
                            <div className="rounded-[8px] border border-[rgba(255,255,255,0.06)] px-2 py-[3px] text-[9px] font-mono text-[var(--color-dark-text-faint)]">
                                {fsmState}
                            </div>
                        </div>
                        {repoNeedsRepair && (
                            <div className="mt-2 rounded-[8px] border border-[var(--tone-warning-border)] bg-[var(--tone-warning-bg)] px-2 py-1.5 text-[10px] text-[var(--tone-warning-text)]">
                                仓库修复优先，部分动作会暂时冻结。
                            </div>
                        )}
                    </div>
                    <div className="app-scrollbar max-h-[330px] overflow-y-auto p-2">
                        {visibleActions.map((action) => {
                            const runnable = isActionRunnable(action);
                            const stateLabel = runStateLabel(action.runState);
                            const percent = progressPercent(action.progress);
                            const progressLines = action.progress?.lines || [];
                            const controls = actionControls(action);
                            return (
                                <div
                                    key={action.id}
                                    className={`w-full rounded-[10px] border px-3 py-2.5 text-left transition-colors ${
                                        runnable
                                            ? 'border-[rgba(255,255,255,0.12)] bg-[rgba(255,255,255,0.045)] hover:bg-[rgba(255,255,255,0.075)]'
                                            : 'border-transparent bg-transparent opacity-72'
                                    }`}
                                >
                                    <div className="flex items-start justify-between gap-3">
                                        <div className="min-w-0">
                                            <div className="truncate text-[12px] font-semibold text-[var(--color-dark-text-main)]">
                                                {action.label}
                                            </div>
                                            <div className="mt-1 text-[10px] leading-4 text-[var(--color-dark-text-muted)]">
                                                {action.description}
                                            </div>
                                            {action.guidance && action.guidance.length > 0 && (
                                                <div className="mt-2 space-y-1 border-l border-[rgba(255,255,255,0.08)] pl-2 text-[9px] leading-4 text-[var(--color-dark-text-faint)]">
                                                    {action.guidance.map((item, index) => (
                                                        <div key={`${action.id}-guide-${index}`}>{item}</div>
                                                    ))}
                                                </div>
                                            )}
                                            <div className="mt-2 flex flex-wrap items-center gap-1.5">
                                                <span className="rounded-full border border-[rgba(255,255,255,0.07)] px-2 py-[2px] text-[9px] text-[var(--color-dark-text-faint)]">
                                                    {action.executionKind === 'direct_job' ? '直接任务' : action.executionKind === 'future_action' ? '预留任务' : '外部专区'}
                                                </span>
                                                {!action.requiresPrompt && (
                                                    <span className="rounded-full border border-[rgba(255,255,255,0.07)] px-2 py-[2px] text-[9px] text-[var(--color-dark-text-faint)]">
                                                        无提示词
                                                    </span>
                                                )}
                                            </div>
                                            {action.meta && (
                                                <div className="mt-1 font-mono text-[9px] text-[var(--color-dark-text-faint)]">
                                                    {action.meta}
                                                </div>
                                            )}
                                        </div>
                                        <span className="shrink-0 rounded-full border border-[rgba(255,255,255,0.07)] px-2 py-[2px] text-[9px] text-[var(--color-dark-text-faint)]">
                                            {stateLabel || statusLabel(action.status)}
                                        </span>
                                    </div>
                                    {action.progress?.mode === 'bar' && action.progress.total > 0 && (
                                        <div className="mt-3">
                                            <div className="flex items-center justify-between text-[9px] text-[var(--color-dark-text-faint)]">
                                                <span>{action.progress.label || '任务进度'}</span>
                                                <span>{percent}%</span>
                                            </div>
                                            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[rgba(255,255,255,0.08)]">
                                                <div
                                                    className="h-full rounded-full bg-[var(--color-accent-blue)] transition-[width] duration-200"
                                                    style={{ width: `${percent}%` }}
                                                />
                                            </div>
                                        </div>
                                    )}
                                    {progressLines.length > 0 && (
                                        <div className="app-scrollbar mt-2 max-h-28 overflow-y-auto rounded-[8px] border border-[rgba(255,255,255,0.06)] bg-[rgba(0,0,0,0.18)] px-2 py-1.5 font-mono text-[9px] leading-4 text-[var(--color-dark-text-muted)]">
                                            {progressLines.slice(-8).map((line, index) => (
                                                <div key={`${action.id}-progress-${index}`}>{line}</div>
                                            ))}
                                        </div>
                                    )}
                                    {controls.length > 0 && (
                                        <div className="mt-3 flex flex-wrap gap-2">
                                            {controls.map((control) => {
                                                const controlRunnable = action.status === 'available' && isControlRunnable(control);
                                                return (
                                                    <button
                                                        key={`${action.id}-control-${control.id}`}
                                                        type="button"
                                                        onClick={controlRunnable ? control.onRun : undefined}
                                                        disabled={!controlRunnable}
                                                        title={control.description}
                                                        className={`rounded-[8px] border px-2.5 py-1.5 text-[10px] font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-45 ${
                                                            control.tone === 'primary'
                                                                ? 'border-[rgba(255,255,255,0.14)] bg-[rgba(255,255,255,0.09)] text-[var(--color-dark-text-main)] hover:bg-[rgba(255,255,255,0.13)]'
                                                                : 'border-[rgba(255,255,255,0.09)] bg-transparent text-[var(--color-dark-text-muted)] hover:bg-[rgba(255,255,255,0.06)]'
                                                        }`}
                                                    >
                                                        {control.label}
                                                    </button>
                                                );
                                            })}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}
            <div className="flex justify-end">
                <button
                    type="button"
                    onMouseDown={handleDragMouseDown}
                    onTouchStart={handleDragTouchStart}
                    onClick={handleToggleClick}
                    className="flex h-11 touch-none cursor-move select-none items-center gap-2 rounded-full border border-[rgba(255,255,255,0.1)] bg-[rgba(16,19,25,0.96)] px-3 text-[12px] font-semibold text-[var(--color-dark-text-main)] shadow-[0_14px_34px_rgba(0,0,0,0.32)] transition-colors hover:bg-[rgba(255,255,255,0.07)]"
                    aria-expanded={open}
                    aria-label="打开工作台动作"
                    title="点击展开；拖动移动"
                >
                    <span className="flex h-6 w-6 items-center justify-center rounded-full border border-[rgba(255,255,255,0.08)] text-[13px]">⌘</span>
                    <span>动作</span>
                    <span className="rounded-full bg-[rgba(255,255,255,0.09)] px-1.5 py-[1px] font-mono text-[10px] text-[var(--color-dark-text-muted)]">
                        {runnableCount}
                    </span>
                </button>
            </div>
        </div>
    );
};
