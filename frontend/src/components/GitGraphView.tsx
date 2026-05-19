import React, { useMemo } from 'react';
import {
    Background,
    Controls,
    Edge,
    MarkerType,
    MiniMap,
    Node,
    Position,
    ReactFlow,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { GitGraphCommit } from '../types/store';

type CommitNodeData = {
    label: string;
    shortHash: string;
    message: string;
    timestamp: string;
    refs: string[];
};

interface GitGraphViewProps {
    commits: GitGraphCommit[];
    selectedCommitId: string | null;
    isLoading: boolean;
    error: string | null;
    onSelectCommit: (commitId: string) => void;
}

const LANE_X_GAP = 260;
const ROW_Y_GAP = 92;

function buildLaneLayout(commits: GitGraphCommit[]): { nodes: Node<CommitNodeData>[]; edges: Edge[] } {
    const laneByCommit = new Map<string, number>();
    const activeLaneTips: Array<string | null> = [];

    function allocateLane(): number {
        const freeIndex = activeLaneTips.findIndex((value) => value === null);
        if (freeIndex >= 0) return freeIndex;
        activeLaneTips.push(null);
        return activeLaneTips.length - 1;
    }

    const nodes: Node<CommitNodeData>[] = [];
    const edges: Edge[] = [];

    commits.forEach((commit, rowIndex) => {
        let lane = laneByCommit.get(commit.commitId);
        if (lane === undefined) {
            lane = allocateLane();
            laneByCommit.set(commit.commitId, lane);
        }

        activeLaneTips[lane] = null;

        const shortHash = commit.commitId.slice(0, 8);
        const normalizedMessage = (commit.message || '(empty message)').replace(/\s+/g, ' ').trim();
        const messagePreview = normalizedMessage.length > 34 ? `${normalizedMessage.slice(0, 34)}...` : normalizedMessage;
        const refsPreview = commit.refs.length > 0 ? ` [${commit.refs[0]}${commit.refs.length > 1 ? '+' : ''}]` : '';
        nodes.push({
            id: commit.commitId,
            position: { x: lane * LANE_X_GAP + 60, y: rowIndex * ROW_Y_GAP + 40 },
            data: {
                label: `${shortHash}  ${messagePreview}${refsPreview}`,
                shortHash,
                message: commit.message,
                timestamp: commit.timestamp,
                refs: commit.refs,
            },
            sourcePosition: Position.Bottom,
            targetPosition: Position.Top,
            draggable: false,
            selectable: true,
            style: {
                width: 232,
                borderRadius: 8,
                border: '1px solid #30363d',
                background: '#0f1722',
                color: '#c9d1d9',
                fontSize: 11,
                fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
                padding: '8px 10px',
            },
            ariaLabel: `${shortHash} ${commit.message}`,
        });

        for (const parentId of commit.parentIds) {
            edges.push({
                id: `${commit.commitId}=>${parentId}`,
                source: commit.commitId,
                target: parentId,
                type: 'smoothstep',
                animated: false,
                markerEnd: { type: MarkerType.ArrowClosed, color: '#8b949e' },
                style: { stroke: '#8b949e', strokeWidth: 1.4 },
            });
        }

        if (commit.parentIds.length > 0) {
            laneByCommit.set(commit.parentIds[0], lane);
            activeLaneTips[lane] = commit.parentIds[0];
            for (const branchParent of commit.parentIds.slice(1)) {
                if (laneByCommit.has(branchParent)) continue;
                const splitLane = allocateLane();
                laneByCommit.set(branchParent, splitLane);
                activeLaneTips[splitLane] = branchParent;
            }
        }
    });

    return { nodes, edges };
}

export const GitGraphView: React.FC<GitGraphViewProps> = ({
    commits,
    selectedCommitId,
    isLoading,
    error,
    onSelectCommit,
}) => {
    const { nodes, edges } = useMemo(() => buildLaneLayout(commits), [commits]);
    const selectedCommit = useMemo(
        () => commits.find((commit) => commit.commitId === selectedCommitId) || null,
        [commits, selectedCommitId]
    );

    if (isLoading) {
        return (
            <div className="flex h-full min-h-0 items-center justify-center text-sm text-[var(--color-dark-text-muted)]">
                Loading Git DAG...
            </div>
        );
    }

    if (error) {
        return (
            <div className="flex h-full min-h-0 items-center justify-center text-sm text-[var(--color-accent-red)]">
                Git DAG 加载失败: {error}
            </div>
        );
    }

    if (commits.length === 0) {
        return (
            <div className="flex h-full min-h-0 items-center justify-center text-sm text-[var(--color-dark-text-muted)]">
                当前仓库暂无可视化提交节点。
            </div>
        );
    }

    return (
        <div className="flex h-full min-h-0 overflow-hidden">
            <div className="min-h-0 flex-1 overflow-hidden bg-[#0b1119]">
                <ReactFlow
                    nodes={nodes.map((node) => ({
                        ...node,
                        style: {
                            ...node.style,
                            borderColor: node.id === selectedCommitId ? 'var(--color-accent-blue)' : '#30363d',
                            boxShadow: node.id === selectedCommitId ? '0 0 0 1px rgba(88,166,255,0.45)' : 'none',
                        },
                    }))}
                    edges={edges}
                    fitView
                    fitViewOptions={{ padding: 0.2 }}
                    nodesDraggable={false}
                    nodesConnectable={false}
                    elementsSelectable
                    onNodeClick={(_, node) => {
                        const commitId = String(node.id);
                        onSelectCommit(commitId);
                        // Minimal phase-1 inspector hook required by product decision.
                        // eslint-disable-next-line no-console
                        console.log('[GitGraph] selected commit:', commitId, node.data);
                    }}
                >
                    <Background gap={18} size={1} color="#1c2530" />
                    <MiniMap
                        pannable
                        zoomable
                        nodeColor={(node) => (node.id === selectedCommitId ? '#58a6ff' : '#2b3540')}
                        maskColor="rgba(1,4,9,0.5)"
                    />
                    <Controls showInteractive={false} />
                </ReactFlow>
            </div>

            <aside className="app-scrollbar w-[300px] min-w-[260px] border-l border-[var(--color-dark-border)] bg-[#0f1722] p-3 text-xs leading-5 text-[var(--color-dark-text-main)] overflow-y-auto">
                <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-dark-text-muted)]">
                    Commit Inspector
                </div>
                {selectedCommit ? (
                    <>
                        <div className="mb-2 break-all font-mono text-[11px] text-[var(--color-accent-blue)]">
                            {selectedCommit.commitId}
                        </div>
                        <div className="mb-3 text-[11px] text-[var(--color-dark-text-muted)]">
                            {selectedCommit.timestamp}
                        </div>
                        <div className="rounded border border-[var(--color-dark-border)] bg-[#0b1119] p-2 text-[12px]">
                            {selectedCommit.message || '(empty commit message)'}
                        </div>
                        {selectedCommit.refs.length > 0 && (
                            <div className="mt-3 flex flex-wrap gap-2">
                                {selectedCommit.refs.map((refName) => (
                                    <span
                                        key={refName}
                                        className="rounded border border-[var(--color-dark-border)] bg-[#111a26] px-2 py-0.5 font-mono text-[10px] text-[var(--color-dark-text-muted)]"
                                    >
                                        {refName}
                                    </span>
                                ))}
                            </div>
                        )}
                    </>
                ) : (
                    <div className="text-[var(--color-dark-text-muted)]">
                        点击任意节点查看基础提交信息。
                    </div>
                )}
            </aside>
        </div>
    );
};
